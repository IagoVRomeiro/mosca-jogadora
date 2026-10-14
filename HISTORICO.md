# Histórico da mosca jogadora

Uma mosca-das-frutas (*Drosophila*) aprendendo a jogar Hollow Knight. O corpo é
o NeuroMechFly (FlyGym), o cérebro pode ser a fiação real do conectoma FlyWire,
e ela joga só vendo a tela e apertando teclas.

Tudo aconteceu em dois dias, 13 e 14/10/2026: 73 commits, 43 versões
treinadas, 488 partidas da mosca (~8,8 h de jogo) registradas no Supabase.

Os horários vêm dos commits do git (a partir de 13/10 18:27) e dos treinos
registrados no Supabase. O que veio antes do primeiro commit está marcado como
**"antes das 18:27"**.

## Onde estamos (14/10, 20:30)

- **Campeã:** #40 (conectoma, o cérebro com a fiação real, **com memória**),
  desde 14/10 ~19:50: venceu a #35 por −7,1 × −18,7 por minuto (+62%).
- **Em disputa:** #43 (rede inventada, com memória).
- **Onde ela treina:** além do save sem progressão, o **Salão dos Deuses** (save
  completo), lutando contra chefes; chefe vencido vale +5.
- **Juiz:** desde 14/10 03:16, um plugin dentro do jogo conta exatamente o que
  aconteceu (dano, cura, morte, geo, golpes, inimigos mortos, sala, posição).
  A leitura pela tela fica de reserva.
- **Ajuda pelo controle:** desde 14/10 12:34 você pode gravar e corrigir pelo
  controle; a mosca aprende as ações e continua jogando pelo teclado.
- **Dados:** 115 gravações suas (89 delas correções ao vivo).

---

## Em uso de quando até quando

Cada solução que foi trocada por outra melhor, com o período em que esteve em uso.

| Função | Solução | Em uso | Substituída por |
|---|---|---|---|
| Ler o que aconteceu no jogo | Leitura do HUD pela tela (máscaras, alma, geo) | antes das 18:27 → 14/10 03:16 | Plugin de dentro do jogo (fica como reserva) |
| Olho da mosca | Versão 1: periferia 18×32 (brilho + movimento) | antes das 18:27 → 13/10 18:56 | Versão 2: periferia + fóvea + memória de ~0,15 s |
| Olho da mosca | Versão 2: memória de ~0,15 s | 13/10 18:56 → 14/10 03:59 | Versão 3: + memória dos últimos segundos (~1 s e ~4 s) |
| Aprender com as gravações | Imitação pura | 13/10 17:59 (treino #1) → 18:37 | Imitação pesada pela recompensa |
| Pesar o que deu certo | Peso pela recompensa | 13/10 18:37 → 21:45 | Peso pela vantagem (AWR, ~3 s de horizonte) |
| Cérebro | Só a rede inventada (mlp) | 13/10 17:59 → 21:16 | mlp e conectoma revezando no torneio |
| Ponto de partida do treino | Cada versão treinada do zero | 13/10 17:59 → 14/10 04:08 | Parte da melhor versão do mesmo cérebro |
| Criar desafiante | Todo treino criava uma | 13/10 19:39 → 14/10 04:08 | Só se aprendeu algo (validação melhor que o ponto de partida) |
| Experiência própria no treino | ~33 min das partidas recentes da mosca | 13/10 19:39 → 14/10 03:53 | ~1,5 h |
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
| Saber o que você aperta | Teclado do sistema (só teclado) | antes das 18:27 → 14/10 12:34 | Ações lidas do jogo pelo plugin (teclado ou controle); sem plugin, teclado |
| Ação "Mapa" (Tab) | A mosca podia abrir o mapa | 13/10 21:30 → 14/10 13:08 | Removida (ela não usava o que via; a exploração vem do plugin) |
| Dados por treino | Cada quadro uma vez | 13/10 17:59 → 14/10 13:26 | Metade espelhada (Esquerda ↔ Direita): quase o dobro de dados |
| Quadros julgados pela tela | Mesmo peso que os do plugin | antes das 18:27 → 14/10 13:26 | Metade do peso |
| Tecla K | Só "Foco" (sempre segurada 1,5 s) | antes das 18:27 → 14/10 13:54 | "Foco" (segurado) e "Magia" (toque) |
| Reflexo de presa | Meia-volta | 13/10 21:38 → 14/10 13:57 | Primeiro tenta escalar; se continuar presa, meia-volta |
| Correções durante uma disputa | Sempre interrompiam a disputa | 14/10 00:52 → 13:57 | Não interrompem se a desafiante estiver na frente |
| Segurar o pulo | Sem limite | antes das 18:27 → 14/10 14:08 | No máximo 0,6 s; querendo mais, solta e aperta de novo |
| Escolher o ponto de partida | A campeã, se do mesmo cérebro | 14/10 04:08 → 18:22 | A melhor na validação entre campeã, desafiante e as 3 mais recentes |
| Fim da disputa | Aos 15 min sem vencer, perde | 13/10 19:39 → 14/10 18:22 | Na frente sem certeza: até 30 min; rodadas vazias não contam |
| Chefe vencido | Igual a um inimigo comum (+1) | 14/10 03:16 → 18:30 | +5 (Salão dos Deuses ou 200+ de vida) |
| Peso das teclas raras no treino | Até 3× para todas | 13/10 19:57 → 14/10 20:13 | Até 15× para habilidades (magia, super investida, ferrão) |
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

## 3. As disputas (13/10 22:32 → 14/10 20:25)

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
| #24 | 14/10 03:42 | mlp | perdeu para a #21 | −15,1 × −4,9 |
| #25 | 14/10 04:02 | conectoma, **com memória**, do zero | interrompida (correção ao vivo; o painel caiu antes de registrar o placar) | — |
| #26 | 14/10 04:17 | conectoma, **com memória**, **partindo da #21** | interrompida, ganhando (correção ao vivo) | −5,3 × −7,9 |
| #27 | 14/10 13:06 | mlp, com memória | interrompida, ganhando | −5,7 × −7,2 |
| #28 | 14/10 13:17 | conectoma, com memória | interrompida | −4,4 × −3,6 |
| **#29** | 14/10 13:20 | **mlp, com memória**, partindo da #27 | **🏆 venceu a #21** (a primeira campeã com memória) | −4,6 × −13,3 (**+65%**) |
| #30 | 14/10 13:36 | conectoma | empate até 15 min → perdeu | −8,1 × −6,8 |
| #31 | 14/10 14:19 | mlp | na frente, sem certeza, aos 15 min → perdeu | −5,8 × −7,6 |
| #32 | 14/10 15:08 | conectoma | empate → perdeu | −7,5 × −7,0 |
| #33 | 14/10 15:42 | mlp | empate → perdeu (7 rodadas vazias) | −4,3 × −3,9 |
| #34 | 14/10 16:16 | conectoma | na frente, sem certeza → perdeu | −6,6 × −8,3 |
| **#35** | 14/10 16:52 | **mlp**, partindo da #29 | **🏆 venceu a #29** | −3,0 × −5,0 (**+39%**) |
| #36 | 14/10 17:09 | conectoma | perdeu | −9,2 × −5,6 |
| #37 | 14/10 17:19 | mlp | empate → perdeu | −7,4 × −7,2 |
| #38 | 14/10 17:54 | conectoma | empate → perdeu | −4,4 × −4,2 |
| #39 | 14/10 18:38 | mlp | empate → perdeu | −7,2 × −7,3 |
| **#40** | 14/10 19:47 | **conectoma**, partindo da #38 | **🏆 venceu a #35** (no Salão dos Deuses) | −7,1 × −18,7 (**+62%**) |
| #41 | 14/10 20:12 | mlp | substituída por um treino seguinte antes de disputar | — |
| #42 | 14/10 20:21 | conectoma | interrompida no começo | — |
| #43 | 14/10 20:25 | mlp | em disputa | — |

A #15 foi a **primeira vitória do cérebro real**, e a #21 o venceu de novo. Depois
vieram duas campeãs mlp com memória (#29 e #35) e de novo o cérebro real (#40).
Entre as vitórias, muitos **empates**: por isso, às 18:22, o torneio passou a dar
mais tempo a quem está na frente e o treino passou a aproveitar quem empatou.

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

## 7. Memória, aprender sempre algo e o controle (14/10, 03:53 → 12:37)

| Data e hora | O que entrou | Ferramenta ou lógica |
|---|---|---|
| 14/10 03:53 | Treino usa ~1,5 h das partidas recentes da mosca (era ~33 min) | com o juiz exato, a experiência dela vale mais |
| 14/10 03:59 | **Olho versão 3: memória dos últimos segundos** | integradores lentos (τ 1 s e 4 s) do brilho da periferia + "quanto a cena mudou" |
| 14/10 04:02 | Primeira mosca com memória (#25, conectoma, do zero) | a memória entra pelas vias de entrada; a fiação real fica igual |
| 14/10 04:08 | **Cada treino parte da melhor versão** do mesmo cérebro e **só disputa quem aprendeu** | pesos copiados ajustando a normalização; ganhos do conectoma recuperados; "nada novo aprendido" sem disputa |
| 14/10 04:17 | #26: a primeira partindo da campeã (#21) | ensaio: validação 0,3607 → 0,3048 na 1ª passada |
| 14/10 12:34 | **Ajudar pelo controle** | o plugin manda as ações acionadas no jogo; teclado ou controle dão no mesmo |
| 14/10 12:37 | `instalar.sh` só lembra da opção da Steam se ela faltar | |

**A memória (03:59).** Até aqui a mosca decidia cada momento lembrando só
~0,15 s, e por isso andava em círculos e insistia em paredes. O olho versão 3
passa a lembrar, de forma resumida, a cena dos últimos segundos, e mede o quanto
a cena de agora difere da lembrada: parada, presa ou em círculos, a cena quase
não muda, e a rede pode aprender a mudar de ideia. De propósito ela **não
lembra das próprias teclas**: na imitação, isso costuma ensinar só a repetir a
última ação.

**Aprender sempre algo (04:08).** Antes, cada desafiante nascia do zero, e o
que a anterior sabia só chegava pelos dados. Agora cada versão começa com os
pesos da melhor do mesmo cérebro (no começo, responde exatamente como ela) e só
vira desafiante se melhorar em dados que o treino não viu. Nenhuma experiência
é jogada fora: partidas, correções e gravações, inclusive de quem perdeu,
entram nos próximos treinos.

**O controle (12:34).** O painel só enxergava o teclado: gravar pelo controle
ensinaria "não fazer nada", e a correção ao vivo não perceberia que você
assumiu. O plugin passou a perguntar ao jogo quais ações estão acionadas
(Pular, Atacar, Esquerda...), venham de onde vierem. A mosca aprende a ação e
continua jogando pelo teclado; as teclas dela, mesmo com o atraso com que o
jogo as vê, nunca contam como suas.

**Uma queda (≈04:07).** A sessão gráfica caiu ("X11 connection broke") e levou
o painel junto, no meio da interrupção da disputa da #25: o placar dela não foi
registrado. O treino que estava rodando terminou sozinho e virou a #26.

## 8. Melhor aproveitamento, combate e o Salão dos Deuses (14/10, 13:08 → 20:13)

| Data e hora | O que entrou | Por quê |
|---|---|---|
| 14/10 13:08 | **Sai o mapa** (ação Tab, hábito, leitor da Bússola) | a mosca não usava o que via e parava de jogar para abri-lo |
| 14/10 13:26 | **Espelho no treino** e **metade do peso** para o que foi julgado pela tela | cada minuto vale quase por dois; a tela perdia golpes e contradizia o plugin |
| 14/10 13:54 | **K dividido em Foco e Magia** | todo K da mosca era segurado: as suas 242 magias por toque viravam cura |
| 14/10 13:57 | **Presa: primeiro tenta escalar**; disputa com desafiante na frente não é interrompida | a meia-volta a afastava de paredes escaláveis; a #26 e a #27 foram interrompidas ganhando |
| 14/10 14:08 | **Pulo segurado no máximo 0,6 s** | para pular de novo agarrada na parede é preciso soltar e apertar |
| 14/10 14:15 | **Banco novo (+1), cura com pouca vida (+0,3 a mais), cair em espinhos/ácido (−1 a mais)** | progresso real, curar quando importa, erro evitável |
| 14/10 14:29 | Primeira gravação pelo **controle** (10 min): as ações chegaram certas | a mosca aprende "Pular", não "botão A" |
| 14/10 18:18 | **Vai e volta pela mesma passagem** (−1) e reflexo de seguir em frente | um vício antigo dela, agora medido pelo nome das salas |
| 14/10 18:22 | **Ponto de partida pela qualidade**, disputa até 30 min para quem está na frente, rodadas vazias não contam | os empates escondiam melhoras pequenas e reais |
| 14/10 18:30 | **Chefe derrotado (+5)** | uma luta longa ganha valia o mesmo que um inimigo comum |
| 14/10 19:35 | Primeiras gravações no **Salão dos Deuses** (Panteão do Mestre, 11 arenas) | combate concentrado |
| 14/10 19:48 | O treino **recupera chefes vencidos** em gravações sem a contagem | a primeira gravação no Salão foi com o plugin antigo: 8 chefes recuperados |
| 14/10 20:13 | **Habilidades raras pesam até 15×** no treino | a magia reproduzida subiu de 20% para 47% das suas |

**O que os dados de combate mostraram (14/10, ~19h).** Comparando as versões com
as suas gravações: ela acertava 2–4 golpes por minuto contra os seus 7, curava
0,2–0,4 vez por minuto contra 1,3, esquivava 3 vezes menos e morria de 6 a 15
vezes mais. A magia praticamente não existia. Daí o foco da tarde: separar a
magia do foco, dar peso às habilidades raras, premiar curar na hora certa e
treinar luta no Salão dos Deuses, onde cada minuto é combate.

**Salão dos Deuses.** Lá a mosca luta contra um chefe de cada vez; você começa a
luta pelo controle, solta, e ela assume. Em cada arena, a última morte é a do
chefe (os ajudantes que ele invoca morrem antes), e o plugin reconhece os chefes
pela lista da própria luta. A #40 venceu a disputa jogando lá.

---

## O que se aprendeu no caminho

- **Recompensa errada ensina errado, e em silêncio.** Quase todo problema do
  comportamento da mosca veio de um estímulo mal medido, não do cérebro. As
  imagens de `diagnostico/` (desde 13/10 22:37) foram o que revelou cada um.
- **O torneio protegeu a mosca dos próprios erros do projeto.** Versões
  treinadas com dados ruins perderam a disputa e nunca jogaram como campeãs.
- **O cérebro real compete bem.** Das cinco trocas de campeã pelo torneio, três
  foram do conectoma (#15, #21, #40) e duas da rede inventada com memória (#29,
  #35).
- **Medir certo vale tanto quanto aprender.** Muitas desafiantes empataram: o
  placar oscila muito (uma morte vale −8), e melhoras pequenas não apareciam.
  Dar mais tempo a quem está na frente e partir da melhor candidata, mesmo sem
  vitória, fez o progresso pequeno se acumular.
- **Dados limpos antes de cérebro maior.** A memória só entrou depois que o
  juiz ficou exato: com recompensas erradas, um cérebro melhor só aprenderia o
  erro mais rápido.

## Próximos passos

1. **Combate no Salão dos Deuses:** um chefe de cada vez, das mais fáceis às
   mais difíceis; gravar lutas com magia (bola de fogo, mergulho e,
   principalmente, o grito, que tem só 17 exemplos), esquiva e cura em segurança.
2. **Correção ao vivo pelo controle** sempre que qualquer versão errar.
3. **Conferir** se o Falso Cavaleiro e os Mestres do Ferrão contam como chefe, o
   equilíbrio das recompensas e o detector de parada.
4. **Se a esquiva continuar fraca:** um prêmio por desviar de golpes com um
   inimigo perto. **Se a magia continuar rara:** um reflexo de magia com a alma
   cheia em combate.
