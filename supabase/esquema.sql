-- Registro do aprendizado da mosca jogadora.
-- Cole tudo no SQL Editor do seu projeto Supabase e rode uma vez.
-- Depois rode também as migrações (migracao_002.sql, ...), em ordem.

-- Cada gravação feita com o botão "⏺ Gravar" (uma pasta em gravacoes/)
create table if not exists public.sessoes (
    id text primary key,                 -- nome da pasta, ex.: 2026-10-13_173436
    gravada_em timestamptz,
    quadros integer not null,
    minutos real not null,
    uso_teclas jsonb not null,           -- {"Esquerda": 0.37, "Pular": 0.11, ...}
    tem_hud boolean not null default false,
    recompensa_total real,               -- soma dos eventos do HUD (null se não tinha HUD)
    quadros_recompensa integer,          -- quadros com evento bom (acerto, geo, cura)
    quadros_punicao integer,             -- quadros com dano
    registrada_em timestamptz not null default now()
);

-- Cada treino (manual ou automático, ao parar uma gravação)
create table if not exists public.treinos (
    id bigint generated always as identity primary key,
    criado_em timestamptz not null default now(),
    quadros integer not null,
    minutos real not null,
    quadros_validacao integer not null,
    perda_validacao real not null,
    epocas integer not null,
    interneuronios integer not null,
    sessoes text[] not null,             -- ids das sessões usadas
    metricas jsonb not null,             -- por tecla: uso, acerto, chute, pega
    modelo_arquivo text                  -- caminho no bucket "modelos"
);

-- Só a chave secreta (usada pelo treinar.py no seu PC) acessa as tabelas:
-- com RLS ligado e sem políticas, a chave pública não lê nem escreve nada.
alter table public.sessoes enable row level security;
alter table public.treinos enable row level security;

-- Bucket privado para os arquivos de modelo (modelo_mosca.npz de cada treino)
insert into storage.buckets (id, name, public)
values ('modelos', 'modelos', false)
on conflict (id) do nothing;
