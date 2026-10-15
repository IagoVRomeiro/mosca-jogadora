"""Treinar a mosca em outro computador (um notebook, sem o jogo).

Os dados que não vão pelo git (gravações, conectoma e modelos) ficam nos arquivos
da release "dados-treino" do GitHub (privada como o repositório), um por sessão:
cada vez só sobe e desce o que mudou. A versão treinada volta pelo Supabase, onde
todo treino já é registrado.

Neste PC (o do jogo):
    .venv-flygym/bin/python notebook.py enviar   # antes de treinar lá
    .venv-flygym/bin/python notebook.py trazer   # depois: a versão nova vira a desafiante

No notebook (depois do git clone ou git pull):
    ./notebook.sh                            # mesmo cérebro da campeã
    ./notebook.sh --arquitetura conectoma    # qualquer opção do treinar.py

Precisa do GitHub CLI (gh) logado nos dois computadores.
"""

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

PASTA = Path(__file__).resolve().parent
RELEASE = "dados-treino"
GRAVACOES, GRAVACOES_MOSCA = PASTA / "gravacoes", PASTA / "gravacoes_mosca"
CONECTOMA = PASTA / "dados_conectoma" / "conectoma_mosca.npz"
MODELOS = ("modelo_mosca.npz", "modelo_mosca.json", "modelo_desafiante.npz", "modelo_desafiante.json")
RECENTE_S = 120  # sessão mexida há menos disto ainda está sendo gravada: fica para a próxima
LOTE = 10  # arquivos por chamada do gh


# --- nomes dos arquivos na release ---

def nome_sessao(sessao, partes):
    """sessao__<id>__<partes>.tar: o número de partes muda se a sessão crescer."""
    return f"sessao__{sessao}__{partes}.tar"


def ler_nome(nome):
    """(id da sessão, partes) de um arquivo de sessão, ou None."""
    if not (nome.startswith("sessao__") and nome.endswith(".tar")):
        return None
    sessao, _, partes = nome[len("sessao__"):-len(".tar")].rpartition("__")
    return (sessao, int(partes)) if sessao and partes.isdigit() else None


def pasta_da_sessao(sessao):
    """Mesmos nomes do treinar.py: as suas pelo nome da pasta, as da mosca com "mosca_"."""
    if sessao.startswith("mosca_"):
        return GRAVACOES_MOSCA / sessao[len("mosca_"):]
    return GRAVACOES / sessao


def sessoes_locais(agora=None):
    """{id: partes} das sessões completas (nada mexido nos últimos RECENTE_S)."""
    agora = time.time() if agora is None else agora
    saida = {}
    for raiz, prefixo in ((GRAVACOES, ""), (GRAVACOES_MOSCA, "mosca_")):
        for pasta in sorted(p for p in raiz.glob("*") if p.is_dir()):
            partes = list(pasta.glob("parte_*.npz"))
            if partes and agora - max(p.stat().st_mtime for p in partes) >= RECENTE_S:
                saida[prefixo + pasta.name] = len(partes)
    return saida


def planejar(locais, remotos):
    """O que subir e o que apagar da release para ela ficar igual às sessões locais.
    `locais`: {id: partes}; `remotos`: nomes dos arquivos na release."""
    na_release = {}
    for nome in remotos:
        lido = ler_nome(nome)
        if lido:
            na_release[lido[0]] = nome
    subir = [s for s, n in locais.items() if na_release.get(s) != nome_sessao(s, n)]
    apagar = [nome for s, nome in na_release.items() if s not in locais or nome != nome_sessao(s, locais[s])]
    return subir, apagar


# --- gh ---

def gh(*args, saida=False):
    r = subprocess.run(["gh", *args], cwd=PASTA, capture_output=saida, text=True)
    if r.returncode:
        raise SystemExit(f"falhou: gh {' '.join(args[:3])}… {r.stderr if saida else ''}")
    return r.stdout if saida else None


def arquivos_da_release():
    """{nome: tamanho}, ou None se a release ainda não existe."""
    r = subprocess.run(["gh", "release", "view", RELEASE, "--json", "assets"], cwd=PASTA,
                       capture_output=True, text=True)
    if r.returncode:
        return None
    return {a["name"]: a["size"] for a in json.loads(r.stdout)["assets"]}


def conferir_gh():
    if shutil.which("gh") is None:
        raise SystemExit("Instale o GitHub CLI (https://cli.github.com) e rode: gh auth login")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        raise SystemExit("Faça login no GitHub antes: gh auth login")


# --- enviar (no PC do jogo) ---

def empacotar(destino, itens):
    """tar sem compressão (os .npz já são comprimidos); caminhos relativos à raiz."""
    with tarfile.open(destino, "w") as tar:
        for item in itens:
            tar.add(item, arcname=str(Path(item).relative_to(PASTA)))


def enviar():
    conferir_gh()
    remotos = arquivos_da_release()
    if remotos is None:
        gh("release", "create", RELEASE, "--prerelease", "--title", "Dados de treino da mosca",
           "--notes", "Gravações, conectoma e modelos para treinar em outro computador "
                      "(notebook.py). Atualizado pelo `notebook.py enviar`; não apague à mão.")
        remotos = {}
    locais = sessoes_locais()
    subir, apagar = planejar(locais, remotos)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fixos = []
        if CONECTOMA.exists():
            nome = f"conectoma__{CONECTOMA.stat().st_size}.tar"
            if nome not in remotos:
                apagar += [n for n in remotos if n.startswith("conectoma__")]
                empacotar(tmp / nome, [CONECTOMA])
                fixos.append(tmp / nome)
        # modelos: sempre (poucos MB), para o notebook partir da campeã e da desafiante de agora
        empacotar(tmp / "modelos.tar", [PASTA / m for m in MODELOS if (PASTA / m).exists()])
        fixos.append(tmp / "modelos.tar")
        gh("release", "upload", RELEASE, *map(str, fixos), "--clobber")
        print(f"{len(locais)} sessões aqui; {len(subir)} para subir, {len(apagar)} velhas para apagar")
        for i in range(0, len(subir), LOTE):
            lote = []
            for s in subir[i:i + LOTE]:
                arquivo = tmp / nome_sessao(s, locais[s])
                empacotar(arquivo, sorted(pasta_da_sessao(s).glob("parte_*.npz")))
                lote.append(arquivo)
            gh("release", "upload", RELEASE, *map(str, lote), "--clobber")
            for arquivo in lote:
                arquivo.unlink()
            print(f"  subiu {min(i + LOTE, len(subir))}/{len(subir)}")
    for nome in apagar:
        gh("release", "delete-asset", RELEASE, nome, "--yes")
    print("Pronto: no notebook, git pull e ./notebook.sh")


# --- treinar (no notebook) ---

def baixar():
    remotos = arquivos_da_release()
    if remotos is None:
        raise SystemExit(f"A release {RELEASE} não existe: rode 'notebook.py enviar' no PC do jogo")
    locais = {}
    for raiz, prefixo in ((GRAVACOES, ""), (GRAVACOES_MOSCA, "mosca_")):
        for pasta in (p for p in raiz.glob("*") if p.is_dir()):
            locais[prefixo + pasta.name] = len(list(pasta.glob("parte_*.npz")))
    faltam = [n for n in remotos if n == "modelos.tar"
              or (n.startswith("conectoma__") and not CONECTOMA.exists())
              or ((lido := ler_nome(n)) and locais.get(lido[0]) != lido[1])]
    print(f"{sum(1 for n in remotos if ler_nome(n))} sessões na release; baixando {len(faltam)} arquivos")
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(0, len(faltam), LOTE):
            lote = faltam[i:i + LOTE]
            gh("release", "download", RELEASE, "-D", tmp, "--clobber", *[a for n in lote for a in ("-p", n)])
            for nome in lote:
                lido = ler_nome(nome)
                if lido:  # sessão que cresceu: troca a pasta inteira
                    shutil.rmtree(pasta_da_sessao(lido[0]), ignore_errors=True)
                with tarfile.open(Path(tmp) / nome) as tar:
                    tar.extractall(PASTA, filter="data")
                (Path(tmp) / nome).unlink()
            print(f"  baixou {min(i + LOTE, len(faltam))}/{len(faltam)}")
    # partidas da mosca que o PC do jogo já apagou (as suas gravações nunca são apagadas)
    na_release = {ler_nome(n)[0] for n in remotos if ler_nome(n)}
    for pasta in (p for p in GRAVACOES_MOSCA.glob("*") if p.is_dir()):
        if "mosca_" + pasta.name not in na_release:
            shutil.rmtree(pasta)


def garantir_env():
    """Sem o Supabase o treino não é registrado e a versão nova não tem como voltar."""
    env = PASTA / ".env"
    if env.exists():
        return
    print("Falta o .env (os mesmos valores do .env do PC do jogo).")
    url = input("SUPABASE_URL: ").strip()
    chave = getpass.getpass("SUPABASE_CHAVE (não aparece ao digitar): ").strip()
    env.write_text(f"SUPABASE_URL={url}\nSUPABASE_CHAVE={chave}\n")
    env.chmod(0o600)


def treinar(opcoes):
    conferir_gh()
    garantir_env()
    baixar()
    r = subprocess.run([sys.executable, "-u", str(PASTA / "treinar.py"), *opcoes], cwd=PASTA)
    if r.returncode == 0 and "--ensaio" not in opcoes:
        print("\nNo PC do jogo, com o painel fechado: .venv-flygym/bin/python notebook.py trazer")
    sys.exit(r.returncode)


# --- trazer (no PC do jogo) ---

def treino_local(arquivo):
    try:
        return json.loads((PASTA / arquivo).read_text()).get("treino_id") or 0
    except (OSError, ValueError):
        return 0


def trazer():
    sys.path.insert(0, str(PASTA))
    from registro import Supabase, baixar_treino

    if subprocess.run(["pgrep", "-f", "jogar.py"], capture_output=True).returncode == 0:
        raise SystemExit("Feche o painel antes (ele guarda os modelos na memória e o placar do torneio)")
    banco = Supabase.do_env()
    if banco is None:
        raise SystemExit("Supabase não configurado (.env)")
    aqui = max(treino_local("modelo_mosca.json"), treino_local("modelo_desafiante.json"))
    # a mais recente que ainda não disputou (uma que já perdeu aqui não volta)
    linhas = banco._pedir("GET", "/rest/v1/treinos?select=id,quadros,config&modelo_arquivo=not.is.null"
                                 "&config->torneio=is.null&order=id.desc&limit=1")
    if not linhas or linhas[0]["id"] <= aqui:
        print(f"Nada novo: o treino mais recente sem disputa no Supabase é o "
              f"#{linhas[0]['id'] if linhas else '?'}, e aqui já está o #{aqui}")
        return
    t = linhas[0]
    arquivo, _ = baixar_treino(t["id"], PASTA / "modelos_base")
    temporario = PASTA / "modelo_desafiante.tmp.npz"
    shutil.copyfile(arquivo, temporario)
    (PASTA / "modelo_desafiante.json").write_text(json.dumps({"treino_id": t["id"], "n_quadros": t["quadros"]}))
    os.replace(temporario, PASTA / "modelo_desafiante.npz")
    cerebro = (t.get("config") or {}).get("arquitetura", "mlp")
    print(f"#{t['id']} ({cerebro}) é a nova desafiante: abra o painel e ligue o 'Controlar jogo' "
          "para ela disputar com a campeã")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("acao", choices=["enviar", "treinar", "trazer", "baixar"])
    args, opcoes = parser.parse_known_args()
    if args.acao == "enviar":
        enviar()
    elif args.acao == "treinar":
        treinar(opcoes)
    elif args.acao == "trazer":
        trazer()
    else:
        conferir_gh()
        baixar()


if __name__ == "__main__":
    main()
