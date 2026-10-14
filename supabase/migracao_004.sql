-- Migração 004: salas novas (exploração) nas partidas da mosca.
-- Rode uma vez no SQL Editor. Pode rodar de novo sem problema.
alter table public.partidas_mosca add column if not exists salas_novas integer not null default 0;
