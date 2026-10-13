"""Envia o aprendizado da mosca para o Supabase.

Configuração: um arquivo .env na pasta do projeto (não vai para o git) com

    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_CHAVE=sb_secret_...

Usa a API REST do Supabase direto (urllib), sem dependências extras. Qualquer
falha vira aviso: o treino nunca quebra por causa do banco.
"""

import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

PASTA = Path(__file__).resolve().parent
ARQUIVO_ENV = PASTA / ".env"


def ler_env(arquivo=ARQUIVO_ENV):
    config = {}
    if arquivo.exists():
        for linha in arquivo.read_text().splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, valor = linha.split("=", 1)
                config[chave.strip()] = valor.strip().strip('"').strip("'")
    return config


class Supabase:
    def __init__(self, url, chave):
        self.url = url.rstrip("/")
        self.chave = chave

    @classmethod
    def do_env(cls):
        """None se o .env não estiver configurado."""
        config = ler_env()
        if config.get("SUPABASE_URL") and config.get("SUPABASE_CHAVE"):
            return cls(config["SUPABASE_URL"], config["SUPABASE_CHAVE"])
        return None

    def _pedir(self, metodo, caminho, corpo=None, cabecalhos=None, tipo="application/json"):
        dados = corpo if isinstance(corpo, bytes) or corpo is None else json.dumps(corpo).encode()
        pedido = urllib.request.Request(f"{self.url}{caminho}", data=dados, method=metodo)
        pedido.add_header("apikey", self.chave)
        pedido.add_header("Authorization", f"Bearer {self.chave}")
        pedido.add_header("Content-Type", tipo)
        for k, v in (cabecalhos or {}).items():
            pedido.add_header(k, v)
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                texto = resposta.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{e.code} em {caminho}: {e.read().decode(errors='replace')}") from None
        return json.loads(texto) if texto else None

    def inserir(self, tabela, linhas, atualizar_se_existir=False):
        preferencia = "return=representation"
        if atualizar_se_existir:
            preferencia += ",resolution=merge-duplicates"
        return self._pedir("POST", f"/rest/v1/{tabela}", linhas, {"Prefer": preferencia})

    def enviar_bytes(self, bucket, caminho, dados):
        return self._pedir(
            "POST", f"/storage/v1/object/{bucket}/{caminho}", dados,
            {"x-upsert": "true"}, tipo="application/octet-stream",
        )

    def enviar_arquivo(self, bucket, caminho, arquivo):
        return self.enviar_bytes(bucket, caminho, Path(arquivo).read_bytes())


def _dados_da_sessao(pasta):
    """Teclas + recompensas + vidas da sessão inteira, sem as telas (poucos KB)."""
    partes = {"teclas": [], "recompensas": [], "vidas": []}
    acoes = None
    for arquivo in sorted(Path(pasta).glob("parte_*.npz")):
        with np.load(arquivo) as parte:
            acoes = parte["acoes"]
            for chave in partes:
                if chave in parte.files:
                    partes[chave].append(parte[chave])
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer, acoes=acoes, **{k: np.concatenate(v) for k, v in partes.items() if v}
    )
    return buffer.getvalue()


def registrar_treino(sessoes, treino, arquivo_modelo, pasta_gravacoes):
    """`sessoes`: linhas de public.sessoes; `treino`: linha de public.treinos sem o
    modelo. Devolve (frase para o log, id do treino ou None)."""
    banco = Supabase.do_env()
    if banco is None:
        return "registro no Supabase desligado (crie o .env com SUPABASE_URL e SUPABASE_CHAVE)", None
    try:
        ja_enviadas = {
            s["id"] for s in banco._pedir("GET", "/rest/v1/sessoes?select=id,dados_arquivo")
            if s.get("dados_arquivo")
        }
        for sessao in sessoes:
            if sessao["id"] in ja_enviadas:
                sessao.pop("dados_arquivo", None)  # não apaga o que já está lá
                continue
            caminho = f"{sessao['id']}.npz"
            banco.enviar_bytes("sessoes", caminho, _dados_da_sessao(Path(pasta_gravacoes) / sessao["id"]))
            sessao["dados_arquivo"] = caminho
        # O upsert exige as mesmas colunas em todas as linhas de um envio
        novas = [s for s in sessoes if "dados_arquivo" in s]
        velhas = [s for s in sessoes if "dados_arquivo" not in s]
        for grupo in (novas, velhas):
            if grupo:
                banco.inserir("sessoes", grupo, atualizar_se_existir=True)

        linha = banco.inserir("treinos", [treino])[0]
        caminho = f"treino_{linha['id']:05d}.npz"
        banco.enviar_arquivo("modelos", caminho, arquivo_modelo)
        banco._pedir(
            "PATCH", f"/rest/v1/treinos?id=eq.{linha['id']}", {"modelo_arquivo": caminho},
            {"Prefer": "return=minimal"},
        )
        return (
            f"registrado no Supabase: treino #{linha['id']} ({len(sessoes)} sessões, "
            f"{len(novas)} com dados novos enviados, modelo em modelos/{caminho})",
            linha["id"],
        )
    except Exception as e:  # sem internet, chave errada, tabela faltando...
        return f"⚠ não consegui registrar no Supabase: {e}", None


def registrar_partida(partida):
    """Envia uma partida da mosca (linha de public.partidas_mosca) numa thread,
    para não travar o painel. Devolve a thread (para esperar no fechamento)."""

    def enviar():
        banco = Supabase.do_env()
        if banco is None:
            return
        try:
            banco.inserir("partidas_mosca", [partida])
            print(f"partida da mosca registrada no Supabase ({partida['segundos']:.0f} s)")
        except Exception as e:
            print(f"⚠ não consegui registrar a partida no Supabase: {e}")

    thread = threading.Thread(target=enviar, daemon=True)
    thread.start()
    return thread
