-- Registro do aprendizado da mosca jogadora (esquema completo, como está hoje).
-- Para um projeto Supabase novo: cole tudo no SQL Editor e rode uma vez.
-- Pode rodar de novo sem problema (tudo é "if not exists").

-- Cada gravação (sua: id = nome da pasta em gravacoes/; da mosca: "mosca_<pasta>")
create table if not exists public.sessoes (
    id text primary key,
    gravada_em timestamptz,
    quadros integer not null,
    minutos real not null,
    uso_teclas jsonb not null,           -- {"Esquerda": 0.37, "Pular": 0.11, ...}
    tem_hud boolean not null default false,
    recompensa_total real,               -- soma dos eventos (null se não tinha HUD)
    quadros_recompensa integer,          -- quadros com evento bom
    quadros_punicao integer,             -- quadros com evento ruim
    dados_arquivo text,                  -- teclas + recompensas quadro a quadro, no bucket "sessoes"
    registrada_em timestamptz not null default now()
);

-- Cada treino (manual ou automático); todo treino gera uma desafiante
create table if not exists public.treinos (
    id bigint generated always as identity primary key,
    criado_em timestamptz not null default now(),
    quadros integer not null,
    minutos real not null,
    quadros_validacao integer not null,
    perda_validacao real not null,
    epocas integer not null,
    interneuronios integer not null,     -- conectoma: número de grupos centrais
    sessoes text[] not null,             -- ids das sessões usadas
    metricas jsonb not null,             -- por tecla: uso, acerto, chute, pega
    config jsonb,                        -- parâmetros, arquitetura, git_commit, torneio
    codigo_versao text,                  -- impressão digital do código
    modelo_arquivo text                  -- caminho no bucket "modelos"
);

-- Cada vez que a mosca joga sozinha (uma rodada do torneio ou o "Controlar jogo")
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
    mortes integer not null default 0,
    danos integer not null,
    acertos integer not null,
    geo integer not null,
    curas integer not null,
    paradas integer not null default 0,
    salas_novas integer not null default 0,
    presas integer not null default 0,   -- ficou presa (parede, pulo que não alcança)
    loops integer not null default 0,    -- andando em círculos
    lugares_mapa integer not null default 0,  -- células novas do mapa (Bússola)
    uso_teclas jsonb not null            -- fração dos quadros com cada tecla apertada
);

-- Só a chave secreta (usada no seu PC) acessa as tabelas: com RLS ligado e sem
-- políticas, a chave pública não lê nem escreve nada.
alter table public.sessoes enable row level security;
alter table public.treinos enable row level security;
alter table public.partidas_mosca enable row level security;

-- Buckets privados: modelos de cada treino e dados leves das sessões
insert into storage.buckets (id, name, public)
values ('modelos', 'modelos', false), ('sessoes', 'sessoes', false)
on conflict (id) do nothing;
