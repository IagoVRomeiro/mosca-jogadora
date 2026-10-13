-- Migração 002: partidas da mosca, configuração dos treinos e dados leves das sessões.
-- Rode uma vez no SQL Editor (depois do esquema.sql). Pode rodar de novo sem problema.

-- Treinos: parâmetros usados e "impressão digital" do código, para comparar treinos
alter table public.treinos add column if not exists config jsonb;
alter table public.treinos add column if not exists codigo_versao text;

-- Sessões: arquivo com teclas + recompensas quadro a quadro (sem as telas)
alter table public.sessoes add column if not exists dados_arquivo text;

-- Cada vez que a mosca joga sozinha ("Controlar jogo" ligado e desligado)
create table if not exists public.partidas_mosca (
    id bigint generated always as identity primary key,
    inicio timestamptz not null,
    fim timestamptz not null,
    segundos real not null,              -- só o tempo em que ela controlava de fato
    quadros integer not null,
    treino_id bigint references public.treinos (id),  -- null = regras fixas, sem treino
    cerebro text not null,
    recompensa_total real not null,
    recompensa_por_minuto real not null,
    danos integer not null,
    acertos integer not null,
    geo integer not null,
    curas integer not null,
    uso_teclas jsonb not null            -- fração dos quadros com cada tecla apertada
);
alter table public.partidas_mosca enable row level security;
-- Punições por ficar parado (3 s sem mexer a tela; repete a cada 2 s)
alter table public.partidas_mosca add column if not exists paradas integer not null default 0;

-- Bucket privado com os dados leves das sessões (sessoes/<id>.npz)
insert into storage.buckets (id, name, public)
values ('sessoes', 'sessoes', false)
on conflict (id) do nothing;
