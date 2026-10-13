"""Prepara o conectoma da mosca para a Fase 5 (cérebro de verdade no lugar do inventado).

Uso (uma vez; leva ~1 min):
    .venv-flygym/bin/python preparar_conectoma.py

Lê o conectoma do FlyWire v783 (Drosophila_brain_model/) e as anotações oficiais
dos neurônios (dados_conectoma/anotacoes_783.tsv, do flyconnectome/flywire_annotations)
e gera dados_conectoma/conectoma_mosca.npz, compacto, com:

- grupos de neurônios por tipo celular e lado do cérebro, em três camadas:
  projeção visual (entrada: LC, LPLC, LLPC... detectores de objetos, aproximação,
  movimento) -> central (só os grupos por onde mais passa sinal do olho até a
  saída) -> descendentes (saída: comandam o corpo);
- as ligações reais entre os grupos (soma das sinapses com sinal: excitatória +,
  inibitória -), normalizadas pela entrada total de cada grupo de destino;
- a posição real de uma amostra de neurônios (para desenhar o cérebro de verdade).

Plano da Fase 5: a rede da mosca passa a ser
    olho -> [aprendida] -> visual -> [fiação do conectoma] -> central
         -> [fiação do conectoma] -> descendentes -> [aprendida] -> teclas
com a fiação real fixa no formato (quem liga em quem e com que sinal) e só a força
geral de cada ligação ajustável. Cada grupo é uma unidade com a atividade média dos
seus neurônios. Simular os 138 mil neurônios um a um em tempo real não cabe.
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

PASTA = Path(__file__).resolve().parent
ARQUIVO_ANOTACOES = PASTA / "dados_conectoma" / "anotacoes_783.tsv"
ARQUIVO_SAIDA = PASTA / "dados_conectoma" / "conectoma_mosca.npz"
MODELO = PASTA / "Drosophila_brain_model"
URL_ANOTACOES = (
    "https://github.com/flyconnectome/flywire_annotations/raw/main/"
    "supplemental_files/Supplemental_file1_neuron_annotations.tsv"
)

GRUPOS_CENTRAIS = 1500  # grupos centrais mantidos (os que mais ligam olho -> saída)
AMOSTRA_DESENHO = 16000  # neurônios com posição, para o desenho do cérebro
CAMADAS = {"visual": "visual_projection", "central": "central", "descendente": "descending"}


def num(x):
    return f"{x:,}".replace(",", ".")


def carregar():
    if not ARQUIVO_ANOTACOES.exists():
        raise SystemExit(
            f"Faltam as anotações dos neurônios. Baixe com:\n"
            f"  mkdir -p dados_conectoma && curl -L -o {ARQUIVO_ANOTACOES.relative_to(PASTA)} {URL_ANOTACOES}"
        )
    ids = pd.read_csv(MODELO / "Completeness_783.csv", index_col=0).index.values
    anotacoes = pd.read_csv(ARQUIVO_ANOTACOES, sep="\t", low_memory=False)
    anotacoes = anotacoes.drop_duplicates("root_id").set_index("root_id").reindex(ids)
    ligacoes = pd.read_parquet(
        MODELO / "Connectivity_783.parquet",
        columns=["Presynaptic_Index", "Postsynaptic_Index", "Excitatory x Connectivity"],
    )
    n = len(ids)
    pesos = sp.csr_matrix(
        (ligacoes["Excitatory x Connectivity"].to_numpy(np.float32),
         (ligacoes.Presynaptic_Index.to_numpy(), ligacoes.Postsynaptic_Index.to_numpy())),
        shape=(n, n),
    )
    return ids, anotacoes, pesos


def agrupar(anotacoes, camada):
    """Índices dos neurônios da camada e o grupo (tipo + lado) de cada um."""
    sel = anotacoes.super_class == CAMADAS[camada]
    indices = np.flatnonzero(sel.to_numpy())
    tipo = anotacoes.cell_type.to_numpy()[indices]
    tipo = np.where(pd.isna(tipo), "sem_tipo", tipo).astype(str)
    lado = anotacoes.side.fillna("na").to_numpy()[indices].astype(str)
    rotulos = np.char.add(np.char.add(tipo, "|"), lado)
    nomes, grupo = np.unique(rotulos, return_inverse=True)
    return indices, nomes, grupo


def pertence(n_neuronios, indices, grupo, n_grupos):
    """Matriz esparsa neurônio -> grupo (1 onde o neurônio é do grupo)."""
    return sp.csr_matrix((np.ones(len(indices), np.float32), (indices, grupo)),
                         shape=(n_neuronios, n_grupos))


def entre_grupos(pesos, de, para):
    """Sinapses com sinal de grupo para grupo, normalizadas pela entrada total
    (em módulo) de cada grupo de destino: cada coluna soma 1 em módulo."""
    m = (de.T @ pesos @ para).toarray()
    total = np.abs(m).sum(axis=0, keepdims=True)
    return (m / np.maximum(total, 1)).astype(np.float32)


def main():
    inicio = time.time()
    ids, anotacoes, pesos = carregar()
    n = len(ids)
    print(f"conectoma: {num(n)} neurônios, {num(pesos.nnz)} ligações")

    camadas = {nome: agrupar(anotacoes, nome) for nome in CAMADAS}
    membros = {nome: pertence(n, i, g, len(nomes)) for nome, (i, nomes, g) in camadas.items()}

    # Grupos centrais por onde mais passa sinal do olho até a saída
    entra = np.abs(membros["visual"].T @ abs(pesos) @ membros["central"]).sum(axis=0).A1
    sai = np.abs(membros["central"].T @ abs(pesos) @ membros["descendente"]).sum(axis=1).A1
    fluxo = np.sqrt(entra * sai)
    manter = np.sort(np.argsort(fluxo)[::-1][:GRUPOS_CENTRAIS])
    _, nomes_c, grupo_c = camadas["central"]
    fica = np.isin(grupo_c, manter)
    novo = -np.ones(len(nomes_c), int)
    novo[manter] = np.arange(len(manter))
    indices_c = camadas["central"][0][fica]
    camadas["central"] = (indices_c, nomes_c[manter], novo[grupo_c[fica]])
    membros["central"] = pertence(n, *camadas["central"][::2], len(manter))
    print(f"central: mantidos {len(manter)} de {len(nomes_c)} grupos "
          f"({num(fica.sum())} de {num(len(fica))} neurônios), {fluxo[manter].sum() / fluxo.sum():.0%} do fluxo")

    ligacoes = {
        "visual_central": entre_grupos(pesos, membros["visual"], membros["central"]),
        "central_central": entre_grupos(pesos, membros["central"], membros["central"]),
        "central_descendente": entre_grupos(pesos, membros["central"], membros["descendente"]),
        "visual_descendente": entre_grupos(pesos, membros["visual"], membros["descendente"]),
    }
    for nome, m in ligacoes.items():
        print(f"ligações {nome}: {m.shape[0]} x {m.shape[1]}, {num(np.count_nonzero(m))} não nulas")

    # Desenho: amostra de neurônios com posição (vista de frente: x lateral, y de cima para baixo)
    rng = np.random.default_rng(0)
    com_posicao = np.flatnonzero(anotacoes.pos_x.notna().to_numpy())
    amostra = np.sort(rng.choice(com_posicao, min(AMOSTRA_DESENHO, len(com_posicao)), replace=False))
    # garante todos os descendentes e boa parte dos visuais no desenho
    amostra = np.union1d(amostra, camadas["descendente"][0])
    posicao = anotacoes[["pos_x", "pos_y"]].to_numpy(np.float32)[amostra]
    classe = anotacoes.super_class.fillna("na").to_numpy()[amostra].astype(str)
    grupo_no_desenho = {}
    for nome, (indices, _, grupo) in camadas.items():
        g = -np.ones(n, np.int32)
        g[indices] = grupo
        grupo_no_desenho[nome] = g[amostra]

    ARQUIVO_SAIDA.parent.mkdir(exist_ok=True)
    np.savez_compressed(
        ARQUIVO_SAIDA,
        **{f"ligacoes_{k}": v for k, v in ligacoes.items()},
        **{f"grupos_{k}": nomes for k, (_, nomes, _) in camadas.items()},
        **{f"tamanho_{k}": np.bincount(g, minlength=len(nomes)) for k, (_, nomes, g) in camadas.items()},
        **{f"desenho_grupo_{k}": v for k, v in grupo_no_desenho.items()},
        desenho_posicao=posicao, desenho_classe=classe, desenho_flywire_id=ids[amostra],
        versao_flywire=783,
    )
    tamanho = ARQUIVO_SAIDA.stat().st_size / 1e6
    print(f"\nsalvo em {ARQUIVO_SAIDA.relative_to(PASTA)} ({tamanho:.1f} MB) em {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    main()
