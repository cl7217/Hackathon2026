create table if not exists public.extraction_batches (
    id uuid primary key,
    created_at timestamptz not null,
    status text not null check (status in ('queued', 'processing', 'complete', 'partial', 'failed')),
    stage text not null default 'ingestion'
        check (stage in ('ingestion', 'classification', 'extraction', 'validation', 'persistence', 'review'))
);

create table if not exists public.extraction_documents (
    id uuid primary key,
    batch_id uuid not null references public.extraction_batches(id) on delete cascade,
    filename text not null,
    status text not null check (status in ('processing', 'complete', 'failed')),
    error text,
    approved boolean not null default false,
    created_at timestamptz not null
);

create table if not exists public.extraction_forms (
    id uuid primary key,
    document_id uuid not null references public.extraction_documents(id) on delete cascade,
    form_type text not null,
    page integer not null check (page > 0),
    approved boolean not null default false,
    unique (document_id, page)
);

create table if not exists public.extraction_fields (
    form_id uuid not null references public.extraction_forms(id) on delete cascade,
    name text not null,
    value_json jsonb,
    raw text,
    page integer,
    bbox_json jsonb,
    source text not null,
    confidence double precision not null check (confidence >= 0 and confidence <= 1),
    state text not null check (state in ('green', 'orange', 'empty')),
    signals_json jsonb not null default '{}'::jsonb,
    handwritten boolean not null default false,
    corrected_by_user boolean not null default false,
    primary key (form_id, name)
);

create index if not exists extraction_documents_batch_created_idx
    on public.extraction_documents (batch_id, created_at);
create index if not exists extraction_forms_document_page_idx
    on public.extraction_forms (document_id, page);
create index if not exists extraction_forms_approved_idx
    on public.extraction_forms (approved);
create index if not exists extraction_fields_name_idx
    on public.extraction_fields (name);

alter table public.extraction_batches enable row level security;
alter table public.extraction_documents enable row level security;
alter table public.extraction_forms enable row level security;
alter table public.extraction_fields enable row level security;

revoke all on public.extraction_batches from anon, authenticated;
revoke all on public.extraction_documents from anon, authenticated;
revoke all on public.extraction_forms from anon, authenticated;
revoke all on public.extraction_fields from anon, authenticated;
grant all on public.extraction_batches to service_role;
grant all on public.extraction_documents to service_role;
grant all on public.extraction_forms to service_role;
grant all on public.extraction_fields to service_role;

create or replace function public.save_extraction(
    p_batch_id uuid,
    p_document_id uuid,
    p_filename text,
    p_forms jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
begin
    insert into public.extraction_documents (
        id, batch_id, filename, status, approved, created_at
    ) values (
        p_document_id, p_batch_id, p_filename, 'complete', false, now()
    );

    insert into public.extraction_forms (id, document_id, form_type, page)
    select
        (form->>'id')::uuid,
        p_document_id,
        form->>'form_type',
        (form->>'page')::integer
    from jsonb_array_elements(p_forms) as forms(form);

    insert into public.extraction_fields (
        form_id, name, value_json, raw, page, bbox_json, source, confidence,
        state, signals_json, handwritten, corrected_by_user
    )
    select
        (form->>'id')::uuid,
        field.name,
        nullif(field.value->'value', 'null'::jsonb),
        field.value->>'raw',
        nullif(field.value->>'page', 'null')::integer,
        field.value->'bbox',
        coalesce(field.value->>'source', 'vlm'),
        coalesce((field.value->>'confidence')::double precision, 0),
        coalesce(field.value->>'state', 'empty'),
        coalesce(field.value->'signals', '{}'::jsonb),
        coalesce((field.value->>'handwritten')::boolean, false),
        coalesce((field.value->>'corrected_by_user')::boolean, false)
    from jsonb_array_elements(p_forms) as forms(form)
    cross join lateral jsonb_each(forms.form->'fields') as field(name, value);
    return jsonb_build_object('saved', true);
end;
$$;

revoke all on function public.save_extraction(uuid, uuid, text, jsonb) from public, anon, authenticated;
grant execute on function public.save_extraction(uuid, uuid, text, jsonb) to service_role;
