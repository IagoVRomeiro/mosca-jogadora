# Mosca Knight 🪰🎮

Uma mosca-das-frutas (*Drosophila melanogaster*) aprendendo a jogar **Hollow Knight**.

O corpo é o modelo biomecânico [NeuroMechFly](https://neuromechfly.org/) (FlyGym + MuJoCo). O cérebro pode ser uma rede neural comum ou a **fiação real do cérebro da mosca**, tirada do conectoma [FlyWire](https://flywire.ai/). Ela joga só **vendo a tela e apertando teclas**, aprende com as partidas gravadas por uma pessoa e com as próprias, e as versões treinadas disputam um torneio para decidir qual joga.

Em poucos dias: 112 commits, 78 versões treinadas, mais de 1.200 partidas da mosca (cerca de 24 h de jogo) e 270 gravações humanas. O diário completo, com cada decisão e o período em que cada solução esteve em uso, está em [HISTORICO.md](HISTORICO.md).

## Como funciona

```
tela do jogo ──► olho ──► cérebro ──► teclas ──► plugin no jogo
                (visão     (rede comum              │
                 da mosca)  ou conectoma)           ▼
                    ▲                         juiz: dano, morte,
                    └──── treino (AWR) ◄────── golpes, sala, posição
```

- **Olho** (`mosca/olho.py`): transforma a tela numa visão de inseto, com periferia de baixa resolução sensível a brilho e movimento, uma fóvea e memória curta (cerca de 0,15 s, 1 s e 4 s).
- **Cérebro** (`mosca/cerebro.py`, `mosca/conectoma.py`): duas arquiteturas revezam.
  - Uma rede inventada (MLP com memória).
  - A fiação do conectoma FlyWire v783: neurônios visuais → centrais → descendentes, agrupados por tipo celular, com as ligações e os sinais (excitatório e inibitório) reais.
- **Aprendizado** (`treinar.py`, `mosca/aprendizado.py`): imitação ponderada pela vantagem (AWR). Cada quadro pesa pelo quanto o resultado foi melhor ou pior que o esperado naquela situação, a mesma ideia do sinal de surpresa da dopamina.
- **Juiz** (`mosca/juiz.py` + plugin BepInEx em `mod/`): um plugin dentro do jogo conta exatamente o que aconteceu (dano, cura, morte, golpes, inimigos, sala, posição, dano no chefe). Ele também aperta as teclas por dentro do jogo e, no Salão dos Deuses, recomeça a luta sozinho.
- **Torneio** (`mosca/orquestrador.py`, `comparar.py`): cada versão nova desafia a campeã; só troca quem joga se vencer com margem maior que a incerteza.
- **Currículo e especialistas** (`mosca/curriculo.py`, `mosca/especialistas.py`): um chefe de cada vez, revisão dos já dominados e um cérebro próprio por arena.
- **Registro** (`registro.py`, `supabase/esquema.sql`): treinos e partidas ficam no Supabase, para treinar em outro computador e acompanhar a evolução.

## Rodando

Feito e testado em **Linux** (X11), com o Hollow Knight pela Steam (Proton) e o BepInEx instalado na pasta do jogo.

1. **Ambiente Python:** crie um ambiente `.venv-flygym` com Python 3 e instale numpy, scipy, pandas, Pillow, PyQt6, pyqtgraph, python-xlib, mujoco e [flygym](https://github.com/NeLy-EPFL/flygym).
2. **Plugin do jogo:** compile `mod/MoscaEventos` (.NET 4.7.2) e rode `mod/instalar.sh`. Na Steam, nas opções de inicialização do Hollow Knight, use `WINEDLLOVERRIDES="winhttp=n,b" %command%`.
3. **Registro (opcional):** copie `.env.exemplo` para `.env` e preencha com o seu projeto Supabase. O `.env` não vai para o Git.
4. **Cérebro de conectoma (opcional):** baixe os dados do FlyWire v783 (veja `preparar_conectoma.py`) para `dados_conectoma/` e rode `.venv-flygym/bin/python preparar_conectoma.py`.
5. **Jogar:**
   - `./iniciar_mosca.sh` abre o jogo e o painel.
   - `.venv-flygym/bin/python jogar.py` roda uma demonstração sem o jogo.
6. **Treinar:**
   - `.venv-flygym/bin/python treinar.py` treina no próprio PC.
   - `./notebook.sh` treina em outro computador.

Testes: `.venv-flygym/bin/python -m unittest discover testes`

## Créditos

- **Corpo da mosca:** [NeuroMechFly / FlyGym](https://github.com/NeLy-EPFL/flygym) (NeLy, EPFL).
- **Conectoma:** [FlyWire](https://flywire.ai/), versão 783. Neurônios e ligações via [philshiu/Drosophila_brain_model](https://github.com/philshiu/Drosophila_brain_model), anotações via [flyconnectome/flywire_annotations](https://github.com/flyconnectome/flywire_annotations). Os dados não estão neste repositório; confira as licenças nas fontes.
- **Jogo:** Hollow Knight é da Team Cherry. Este projeto não inclui nenhum arquivo do jogo.

Feito por [Iago Verciano Romeiro](https://github.com/IagoVRomeiro), estudante de Engenharia da Computação na PUC Minas.
