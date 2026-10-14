# Histórico da mosca jogadora

Uma mosca-das-frutas (*Drosophila*) aprendendo a jogar Hollow Knight. O corpo é
o NeuroMechFly (FlyGym), o cérebro pode ser a fiação real do conectoma FlyWire,
e ela joga só vendo a tela e apertando teclas.

Tudo aconteceu em dois dias, 13 e 14/10/2026: 54 commits, 24 versões
treinadas, 141 partidas da mosca (~2,5 h de jogo) registradas no Supabase.

Os horários vêm dos commits do git (a partir de 13/10 18:27) e dos treinos
registrados no Supabase. O que veio antes do primeiro commit está marcado como
**"antes das 18:27"**.

## Onde estamos (14/10, 03:45)

- **Campeã:** #21 (conectoma, o cérebro com a fiação real), desde 14/10 01:52.
- **Em disputa:** #24 (rede inventada, "mlp"), treinada sozinha às 03:42.
- **Juiz:** desde 14/10 03:16, um plugin dentro do jogo conta exatamente o que
  aconteceu (dano, cura, morte, geo, golpes, inimigos mortos, sala, posição).
  A leitura pela tela fica de reserva.
- **Dados:** 24 gravações suas (5 delas correções ao vivo), 1,4 GB.

---

## Em uso de quando até quando

Cada solução que foi trocada por outra melhor, com o período em que esteve em uso.

| Função | Solução | Em uso | Substituída por |
|---|---|---|---|
| Ler o que aconteceu no jogo | Leitura do HUD pela tela (máscaras, alma, geo) | antes das 18:27 → 14/10 03:16 | Plugin de dentro do jogo (fica como reserva) |
| Olho da mosca | Versão 1: periferia 18×32 (brilho + movimento) | antes das 18:27 → 13/10 18:56 | Versão 2: periferia + fóvea + memória de ~0,15 s |
| Aprender com as gravações | Imitação pura | 13/10 17:59 (treino #1) → 18:37 | Imitação pesada pela recompensa |
| Pesar o que deu certo | Peso pela recompensa | 13/10 18:37 → 21:45 | Peso pela vantagem (AWR, ~3 s de horizonte) |
| Cérebro | Só a rede inventada (mlp) | 13/10 17:59 → 21:16 | mlp e conectoma revezando no torneio |
| Trocar a versão que joga | Treinou, já joga | 13/10 17:59 → 19:39 | Torneio campeã × desafiante |
| Veredito do torneio | Margem fixa | 13/10 19:39 → 20:04 | Margem + 2× incerteza para vencer |
| Regra para perder | Atrás 0,5/min já perde | 13/10 20:04 → 14/10 02:02 | Só perde cedo se atrás com segurança (simétrica) |
| Morte | Não detectada (renascer virava cura) | antes das 18:27 → 13/10 20:04 | Morte pelo HUD |
| Sala nova | Fotos da entrada da sala | 13/10 21:30 → 14/10 03:16 | Nome real da sala, pelo plugin |
| Saber onde ela está | Hábito de abrir o mapa (Tab) a cada 45 s + marca da Bússola | 13/10 21:30 / 22:50 → 14/10 03:25 | Posição exata pelo plugin |
| Presa na parede | Deslizamento da câmera | 13/10 21:38 → 14/10 03:34 | Posição real (plugin) |
| Andando em círculos | Câmera indo e voltando | 13/10 22:55 → 14/10 03:34 | Posição real (plugin) |
| Parada | Movimento médio da imagem | antes das 18:27 → 14/10 03:34 | Velocidade real (plugin) |
| Golpe acertado | Alma subindo de repente | antes das 18:27 → 14/10 03:16 | Cada golpe, pelo plugin (de ~1,5 para ~13 por minuto) |
| Treinar depois de gravar | Esperava a disputa acabar | 13/10 22:50 → 14/10 00:52 | Treina na hora, interrompendo a disputa |
| Ligar e desligar | Botões do painel | antes das 18:27 → 14/10 01:00 | Atalhos Ctrl+Alt+G / Ctrl+Alt+C (os botões continuam) |
| Gravações | Recompensa já somada por quadro | antes das 18:27 → 14/10 02:21 | Marcas de evento (02:21) → contagem de cada evento + pesos + estado do jogo (03:31) |

---

## 1. Os primeiros passos (13/10, antes das 18:27)

O projeto começou com uma pergunta: dá para treinar a mesma mosca em vários
jogos, começando pelo Hollow Knight? Antes do primeiro commit já existiam:

- **O painel** (PyQt6 + pyqtgraph). A ideia inicial eram três janelas (jogo,
  mosca 3D, neurônios); ficou um painel no estilo de uma imagem de referência:
  **01 Pintar o cérebro** (neurônios que dá para estimular com um pincel) e
  **02 Veja a resposta** (a mosca 3D). A janela "Jogo" saiu: o painel só captura
  a janela da Steam.
- **A mosca 3D na frente do PC** (FlyGym/MuJoCo, renderizada fora da tela por
  EGL), apertando as teclas com as patas, com o jogo de verdade no monitor.
- **Captura e teclas.** A imagem do jogo vem da janela pelo X11 (python-xlib);
  as teclas são simuladas por **XTEST**, como um teclado físico, só com o
  Hollow Knight em foco: nunca digita em outro programa.
- **Todas as ações do jogo** nas suas teclas: A/D/W/S, Space, H (ataque),
  J (esquiva), K (foco), L (super investida), N (ferrão dos sonhos),
  M (magia rápida), Tab (mapa).
- **Gravar para ensinar:** você joga, o painel grava a tela (em cinza, para
  ocupar menos) e as suas teclas.
- **Estímulos pelo HUD**, lidos pela tela: dano é ruim; acertar e pegar geo é
  bom; ficar parada é ruim.
- **Supabase** (projeto "mosca knight"): treinos, sessões e partidas registrados
  por REST, com a chave só no `.env`. Repositório privado no GitHub.

**Treinos #1 (17:59), #2 (18:12) e #3 (18:23):** imitação pura das suas
gravações, de 24 mil a 47 mil quadros.

## 2. A mosca aprende de verdade (13/10, 18:27–23:13)

| Data e hora | O que entrou | Ferramenta ou lógica |
|---|---|---|
| 13/10 18:27 | Primeiro commit: painel, mosca 3D, imitação, Supabase | `jogar.py`, `treinar.py`, `registro.py` |
| 13/10 18:37 | **Fase 2:** imitação pesada pela recompensa | o que veio antes de um prêmio pesa mais |
| 13/10 18:39 | Jogar uma versão antiga: `jogar.py --treino N` | modelo baixado do Supabase |
| 13/10 18:42 | Comparar versões pelas partidas | `comparar.py` |
| 13/10 18:56 | **Fase 3:** olho versão 2 | periferia + fóvea + tela de 5 quadros antes |
| 13/10 19:12 | Reflexo de sair do lugar | parada demais: tenta andar ou pular |
| 13/10 19:39 | **Fase 4:** aprende jogando, **torneio campeã × desafiante** | rodadas alternadas de 1 min |
| 13/10 19:57 | Ataque em toques repetidos, Foco segurado 1,5 s | ela não conseguia atacar nem curar |
| 13/10 20:04 | Morte pelo HUD, torneio estatístico, testes automáticos | vence só com margem > 2× a incerteza |
| 13/10 20:08 | "De X para Y houve W% de melhoria" | `comparar.py X Y` |
| 13/10 20:21 | Código em módulos (`mosca/`) e conectoma preparado | `preparar_conectoma.py` (dados FlyWire 783) |
| 13/10 21:16 | **Fase 5:** cérebro com a **fiação real da mosca** | `RedeConectoma`: visual → central → descendente |
| 13/10 21:17 | Zonas de comando: 10 grupos descendentes reais por tecla | neurônios que levam o comando ao corpo |
| 13/10 21:30 | Exploração: Tab, hábito do mapa, prêmio por sala nova | foto da entrada da sala |
| 13/10 21:38 | Detector de **presa** | deslizamento da câmera (correlação de fase) |
| 13/10 21:45 | Peso pela **vantagem (AWR)**, cache do olho | estimador de valor, horizonte de ~3 s |
| 13/10 21:51 | Protótipos antigos removidos | `painel.py`, `mosca3d.py` |
| 13/10 22:37 | **Modo diagnóstico** | foto antes/depois de cada evento em `diagnostico/` |
| 13/10 22:41 | HUD escurecido não vira mais morte | mapa aberto, transição, menu |
| 13/10 22:42 | Treino ignora as mortes falsas antigas | uma sessão tinha 29 |
| 13/10 22:50 | Mapa pela **Bússola Errante**; revezamento mlp/conectoma; treino espera a disputa | marca achada por correlação |
| 13/10 22:55 | Detector de **loop** (andando em círculos) | câmera indo e voltando sem nada de bom |
| 13/10 23:02 | Painel de **evolução** | `evolucao.py` |
| 13/10 23:07 | Partidas registram presas, loops e lugares no mapa | colunas novas no Supabase |
| 13/10 23:11 | Abre tudo com um clique ou **Ctrl+Alt+M** | `iniciar_mosca.sh` + atalho do GNOME |
| 13/10 23:13 | Sala nova não dá mais para burlar | ela estava viciada em entrar e sair |

**Por que o torneio (19:39):** ele nasceu de uma regra sua, *"se tem chance de
piora, não faça"*. Todo treino gera uma **desafiante**, e a **campeã** só é
trocada se a desafiante jogar comprovadamente melhor. Assim a mosca aprende
sozinha sem nunca piorar quem está jogando.

**Os dois cérebros (desde 21:16):** a rede inventada ("mlp") e o conectoma, em
que neurônios e ligações são os da mosca real e só a força de cada grupo é
aprendida. O primeiro conectoma foi o treino #12, às 21:15.

## 3. As disputas (13/10 22:32 → 14/10 03:42)

| Versão | Treinada em | Cérebro | Resultado | Recompensa/min (desafiante × campeã) |
|---|---|---|---|---|
| #14 | 13/10 22:32 | mlp | interrompida em 23:28 (pesos mudaram) | −0,8 × −5,6 (contra #6) |
| **#15** | 13/10 23:31 | **conectoma** | **🏆 venceu a #6** | −1,4 × −4,3 (**+67%**) |
| #16 | 13/10 23:49 | mlp | perdeu | −2,6 × −2,0 |
| #17 | 14/10 00:22 | conectoma | interrompida (gravação nova) | −3,2 × −0,2 |
| #18 | 14/10 00:54 | mlp | perdeu | −4,4 × −1,7 |
| #19 | 14/10 01:27 | conectoma | interrompida | −3,8 × −2,2 |
| #20 | 14/10 01:41 | mlp | perdeu | −3,5 × −2,8 |
| **#21** | 14/10 01:52 | **conectoma** | **🏆 venceu a #15** | −2,6 × −4,0 (**+34%**) |
| #22 | 14/10 02:48 | conectoma | não disputou (vida lida errada) | — |
| #23 | 14/10 02:53 | conectoma | perdeu para a #21 | −13,2 × −5,4 |
| #24 | 14/10 03:42 | mlp | em disputa | — |

A #15 foi a **primeira vitória do cérebro real**, e a #21 o venceu de novo: as
duas campeãs desde então são da fiação da mosca de verdade.

## 4. Ajustes de comportamento (13/10 23:28 → 14/10 01:12)

| Data e hora | O que mudou | Por quê |
|---|---|---|
| 13/10 23:28 | Presa e loop −0,3 → −0,6; meia-volta com 4 s encostada | era o maior problema dela |
| 14/10 00:10 | Saem os botões Pausar e Reiniciar | sobras da fase de demonstração |
| 14/10 00:22 | Painel com 1 thread de contas; treino com metade dos núcleos, prioridade baixa | o jogo perdia FPS (12 threads girando à toa) |
| 14/10 00:28 | Tab segurado no máximo 3 s, depois descansa 10 s | ela abria o mapa e não soltava mais |
| 14/10 00:31 | Cérebro sem letras amontoadas; o mouse num botão mostra a zona | no conectoma as zonas ficam todas no centro |
| 14/10 00:52 | Parar a gravação treina na hora | antes esperava a disputa acabar |
| 14/10 01:00 | Atalhos **Ctrl+Alt+G** (gravar) e **Ctrl+Alt+C** (mosca joga) | sinais para o painel (`atalho_mosca.sh`) |
| 14/10 01:03 | Atalhos no rodapé do painel | para não precisar lembrar |
| 14/10 01:12 | Escalar parede não é presa | o save tem a Garra de Louva-a-deus |

## 5. Correção ao vivo e juiz mais justo (14/10, 02:02 → 02:57)

| Data e hora | O que mudou |
|---|---|
| 14/10 02:02 | **Correção ao vivo:** pegar o teclado quando ela erra. O trecho vira correção (peso 1,5), ela volta 2 s depois que você solta, a ajuda em apuros vira estímulo ruim, toque < 1 s é descartado. **Regra de perder simétrica.** |
| 14/10 02:21 | **Dano −2 e morte −8** (antes −1 e −3: ficar parada e andar em círculos puniam mais que morrer). Gravações passam a marcar dano e morte. |
| 14/10 02:25 | Mapa reconhece a área em qualquer tamanho de janela; o treino registra antes de pôr a desafiante no lugar. |
| 14/10 02:30 | Pontos verdes e vermelhos no cérebro só durante um estímulo de verdade. |
| 14/10 02:46 | Corrigido o erro que quebrava o fim do treino (desafiante sem número, treino de uma gravação sua sem terminar). |
| 14/10 02:49 | **Máscara tremendo** com 1 de vida não vira mais cura + dano falsos (~160 pares em 3 h de gravações; a #22 foi descartada por isso). |
| 14/10 02:57 | Geo: o "+N" sumindo e o geo zerado depois de morrer não contam mais. |

## 6. O juiz de dentro do jogo (14/10, 03:03 → 03:45)

Os erros da tela levaram à grande mudança do dia: em vez de adivinhar pela
imagem, perguntar ao próprio jogo.

| Data e hora | O que entrou | Ferramenta ou lógica |
|---|---|---|
| 14/10 03:03 | BepInEx 5.4.23.5 na pasta do jogo; .NET 8 para compilar | a Modding API só roda na versão antiga do jogo (1.5.78); o seu é a 1.5.12620 (Unity 6) |
| 14/10 03:11 | Plugin `mod/MoscaEventos`, compilado | Harmony: dano e morte de inimigos; estado 30×/s por UDP local |
| 14/10 03:13 | Primeiro teste: o BepInEx carregou e o plugin mandou dados | opção de inicialização na Steam |
| 14/10 03:16 | **Painel usa o juiz** quando o plugin está mandando | `mosca/juiz.py`; sem plugin, volta para a tela |
| 14/10 03:17 | Carregar o save não é sala nova | |
| 14/10 03:20 | Renascer no banco não é sala nova | |
| 14/10 03:25 | Com o plugin, a mosca não para mais para olhar o mapa | o mapa servia só ao painel |
| 14/10 03:31 | Gravações guardam a contagem de cada evento, os pesos e o **estado do jogo** | mudar um peso vale exato para gravações já feitas |
| 14/10 03:34 | **Parada, presa, loop e lugar novo pela posição real** | `DetectoresPelaPosicao` |
| 14/10 03:45 | Limpeza do que ficou sem uso | |

**A mosca continua vendo só a tela.** O plugin só substitui o juiz. Logo na
primeira conferência, todas as imagens de dano, morte, cura, golpe e inimigo
morto bateram com o que aconteceu.

**Recompensas novas com o plugin (03:16 e 03:34):** inimigo morto (+1), sala
nova pelo nome real (+1, impossível de burlar), lugar novo dentro da sala
(+0,2), geo só quando sobe, cura só com o Foco.

---

## O que se aprendeu no caminho

- **Recompensa errada ensina errado, e em silêncio.** Quase todo problema do
  comportamento da mosca veio de um estímulo mal medido, não do cérebro. As
  imagens de `diagnostico/` (desde 13/10 22:37) foram o que revelou cada um.
- **O torneio protegeu a mosca dos próprios erros do projeto.** Versões
  treinadas com dados ruins perderam a disputa e nunca jogaram como campeãs.
- **O cérebro real compete bem.** As duas trocas de campeã pelo torneio (#15 e
  #21) foram do conectoma.

## Próximos passos

1. **Mais dados bons:** deixar a mosca jogar e corrigir ao vivo; gravar lutas e
   exploração, agora premiadas com exatidão.
2. **Memória de alguns segundos:** hoje ela lembra ~0,15 s, e por isso anda em
   círculos e insiste em paredes.
3. **Menos peso às gravações antigas,** julgadas pela tela.
4. **Ajuste fino dos detectores pela posição** com o jogo de verdade.
