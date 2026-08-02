-- ============================================================================
-- QR Queue — Enterprise Schema for Supabase (PostgreSQL)
-- Run this in: Supabase Dashboard -> SQL Editor -> New query
-- ============================================================================

create extension if not exists "pgcrypto";   -- gen_random_uuid()

-- ----------------------------------------------------------------------------
-- 1. ORGANIZATIONS  (รองรับหลายโรงพยาบาล / หลาย tenant บนระบบเดียว)
-- ----------------------------------------------------------------------------
create table if not exists organizations (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    created_at  timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- 2. BRANCHES  (สาขา / อาคาร / วิทยาเขต ของแต่ละองค์กร)
-- ----------------------------------------------------------------------------
create table if not exists branches (
    id              uuid primary key default gen_random_uuid(),
    organization_id uuid not null references organizations(id) on delete cascade,
    name            text not null,
    address         text,
    timezone        text not null default 'Asia/Bangkok',
    is_active       boolean not null default true,
    created_at      timestamptz not null default now()
);

create index if not exists idx_branches_org on branches(organization_id);

-- ----------------------------------------------------------------------------
-- 3. QUEUE_TYPES  (แผนก/ห้องตรวจ ต่อสาขา)
-- ----------------------------------------------------------------------------
create table if not exists queue_types (
    id          uuid primary key default gen_random_uuid(),
    branch_id   uuid not null references branches(id) on delete cascade,
    name        text not null,
    prefix      text not null,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),
    unique (branch_id, prefix)
);

create index if not exists idx_queue_types_branch on queue_types(branch_id);

-- ----------------------------------------------------------------------------
-- 4. STAFF  (ผูกกับ Supabase Auth ผ่าน auth_user_id — ดูหมายเหตุด้านล่าง)
-- ----------------------------------------------------------------------------
create table if not exists staff (
    id              uuid primary key default gen_random_uuid(),
    auth_user_id    uuid unique references auth.users(id) on delete set null,
    branch_id       uuid references branches(id) on delete set null,
    organization_id uuid references organizations(id) on delete set null,
    username        text unique not null,
    password_hash   text,                       -- เก็บไว้เผื่อ fallback / legacy login
    role            text not null default 'staff'
                        check (role in ('super_admin','org_admin','branch_admin','staff')),
    is_active       boolean not null default true,
    created_at      timestamptz not null default now()
);

create index if not exists idx_staff_branch on staff(branch_id);

-- ----------------------------------------------------------------------------
-- 5. TICKET_COUNTERS  (ตัวนับเลขคิวแบบ atomic — แก้ปัญหา race condition เดิม)
-- ----------------------------------------------------------------------------
create table if not exists ticket_counters (
    queue_type_id   uuid not null references queue_types(id) on delete cascade,
    the_date        date not null,
    last_number     integer not null default 0,
    primary key (queue_type_id, the_date)
);

-- ฟังก์ชันออกเลขคิวแบบ atomic ระดับ database (กันเลขซ้ำเวลามีคนกดพร้อมกันจำนวนมาก)
create or replace function next_ticket_number(p_queue_type_id uuid, p_date date)
returns integer
language plpgsql
as $$
declare
    v_number integer;
begin
    insert into ticket_counters (queue_type_id, the_date, last_number)
    values (p_queue_type_id, p_date, 1)
    on conflict (queue_type_id, the_date)
    do update set last_number = ticket_counters.last_number + 1
    returning last_number into v_number;
    return v_number;
end;
$$;

-- ----------------------------------------------------------------------------
-- 6. TICKETS  (หัวใจของระบบ)
-- ----------------------------------------------------------------------------
create table if not exists tickets (
    id              bigint generated always as identity primary key,
    queue_number    text not null,
    queue_type_id   uuid not null references queue_types(id),
    branch_id       uuid not null references branches(id),
    status          text not null default 'waiting'
                        check (status in ('waiting','in_service','done','skipped')),
    priority        text not null default 'normal'
                        check (priority in ('normal','urgent')),
    called_by       uuid references staff(id),
    created_at      timestamptz not null default now(),
    called_at       timestamptz,
    completed_at    timestamptz
);

-- ดัชนีที่จำเป็นสำหรับโหลดสูง (หลายพันคิว/วัน, หลายสาขาพร้อมกัน)
create index if not exists idx_tickets_type_status  on tickets(queue_type_id, status);
create index if not exists idx_tickets_branch_status on tickets(branch_id, status);
create index if not exists idx_tickets_created_at    on tickets(created_at);
create index if not exists idx_tickets_status_created on tickets(status, created_at)
    where status = 'waiting';   -- partial index เร่ง query "คิวที่รออยู่" ให้เร็วมากแม้ข้อมูลสะสมหลักล้าน

-- ----------------------------------------------------------------------------
-- 7. AUDIT_LOG  (ใครทำอะไร เมื่อไหร่ — จำเป็นสำหรับองค์กรที่ต้อง audit/compliance)
-- ----------------------------------------------------------------------------
create table if not exists audit_log (
    id          bigint generated always as identity primary key,
    staff_id    uuid references staff(id),
    branch_id   uuid references branches(id),
    action      text not null,          -- e.g. 'call_next', 'complete', 'skip', 'login'
    entity      text,                   -- e.g. 'ticket:123'
    details     jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists idx_audit_branch_time on audit_log(branch_id, created_at);

-- ----------------------------------------------------------------------------
-- 8. ROW LEVEL SECURITY
-- แนวทาง: แอป Flask เชื่อมต่อผ่าน service_role key (ฝั่ง server เท่านั้น) จึง bypass RLS
-- ได้ตามปกติ — RLS ที่เปิดไว้นี้คือ "เกราะชั้นสอง" ป้องกันกรณีมีการเรียก Supabase REST/JS
-- API ตรงจาก client (เช่น ถ้าในอนาคตทำ dashboard แบบ realtime บนเบราว์เซอร์)
-- ----------------------------------------------------------------------------
alter table tickets        enable row level security;
alter table queue_types    enable row level security;
alter table staff          enable row level security;
alter table branches       enable row level security;
alter table audit_log      enable row level security;

-- อ่านสถานะคิวสาธารณะได้ (หน้าจอทีวี/หน้าติดตามคิวของคนไข้) แต่แก้ไขไม่ได้ตรง ๆ
create policy "public can read tickets" on tickets
    for select using (true);

create policy "public can read queue_types" on queue_types
    for select using (true);

-- staff เห็น/แก้ได้เฉพาะข้อมูล branch ตัวเอง (ยกเว้น super_admin/org_admin)
create policy "staff manage own branch tickets" on tickets
    for all using (
        exists (
            select 1 from staff s
            where s.auth_user_id = auth.uid()
              and s.is_active
              and (s.role in ('super_admin') or s.branch_id = tickets.branch_id)
        )
    );

-- ----------------------------------------------------------------------------
-- 9. REALTIME  — เปิดให้ตาราง tickets ส่ง event แบบ push แทนการ polling ทุก 5 วิ
-- ----------------------------------------------------------------------------
alter publication supabase_realtime add table tickets;

-- ----------------------------------------------------------------------------
-- 10. SEED ตัวอย่าง (ลบ/แก้ตามองค์กรจริง)
-- ----------------------------------------------------------------------------
insert into organizations (id, name)
values ('00000000-0000-0000-0000-000000000001', 'โรงพยาบาลตัวอย่าง')
on conflict (id) do nothing;

insert into branches (id, organization_id, name)
values ('00000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'สาขาหลัก')
on conflict (id) do nothing;

insert into queue_types (branch_id, name, prefix)
select '00000000-0000-0000-0000-000000000011', name, prefix
from (values
    ('ซักประวัติ / วัดความดัน', 'A'),
    ('ตรวจโรคทั่วไป', 'B'),
    ('เจาะเลือด / เอกซเรย์', 'C'),
    ('รับยา / การเงิน', 'D'),
    ('ทันตกรรม', 'E')
) as t(name, prefix)
where not exists (
    select 1 from queue_types q
    where q.branch_id = '00000000-0000-0000-0000-000000000011' and q.prefix = t.prefix
);
