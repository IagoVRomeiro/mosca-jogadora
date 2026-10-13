-- Migração 003: mortes nas partidas da mosca.
-- Rode uma vez no SQL Editor. Pode rodar de novo sem problema.
alter table public.partidas_mosca add column if not exists mortes integer not null default 0;
