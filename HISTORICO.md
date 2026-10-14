# Histórico da mosca jogadora

Uma mosca-das-frutas (*Drosophila*) aprendendo a jogar Hollow Knight. O corpo é
o NeuroMechFly (FlyGym), o cérebro pode ser a fiação real do conectoma FlyWire,
e ela joga só vendo a tela e apertando teclas.

Tudo aconteceu em dois dias, 13 e 14/10/2026: 54 commits, 24 versões
treinadas, 141 partidas da mosca (~2,5 h de jogo) registradas no Supabase.

## Onde estamos (14/10, 03:45)

- **Campeã:** #21 (conectoma, o cérebro com a fiação real), desde 01:52 de 14/10.
- **Em disputa:** #24 (rede inventada, "mlp"), treinada sozinha às 03:42.
- **Juiz:** um plugin dentro do jogo conta exatamente o que aconteceu (dano, cura,
  morte, geo, golpes, inimigos mortos, sala, posição). A leitura pela tela fica
  de reserva.
- **Dados:** 24 gravações suas (5 delas correções ao vivo), 1,4 GB.

---

## 1. Os primeiros passos (13/10, tarde)

O projeto começou com uma pergunta: dá para treinar a mesma mosca em vários
jogos, começando pelo Hollow Knight?

- **Três janelas viraram um painel.** A ideia inicial era uma janela para o
  jogo, uma para a mosca 3D e outra para os neurônios. Ficou um painel no estilo
  de uma imagem de referência: **01 Pintar o cérebro** (os neurônios, onde dá
  para estimular regiões com um pincel) e **02 Veja a resposta** (a mosca 3D).
- **A mosca na frente do PC.** A mosca 3D foi posta presa diante de um
  computador, apertando as teclas com as patas, com o jogo de verdade no monitor.
- **A janela "Jogo" saiu.** O jogo já roda na própria janela da Steam; o painel
  só captura a imagem dela.
- **Todas as ações do jogo,** com as suas teclas: andar (A/D/W/S), pular (Space),
  atacar (H), esquiva (J), foco (K), super investida (L), ferrão dos sonhos (N),
  magia rápida (M) e mapa (Tab). As teclas mudaram duas vezes no caminho.
- **Teclas de verdade no jogo.** O Proton ignorava teclas sem foco; passou a
  usar XTEST (como um teclado físico), só com o Hollow Knight em foco: nunca
  digita em outro programa.
- **Gravar para ensinar.** Você joga, o painel grava a tela e as suas teclas, e
  ao parar a gravação a mosca treina sozinha. As gravações viraram cinza para
  ocupar menos espaço.
- **Estímulos bons e ruins.** O HUD (máscaras de vida, alma, geo) passou a ser
  lido pela tela: dano é ruim, acertar e pegar geo é bom.
- **Supabase.** Projeto "mosca knight": cada treino, sessão e partida fica
  registrado, e qualquer versão antiga pode ser baixada e jogada de novo
  (`jogar.py --treino N`), para mostrar o antes e o depois.
- **Privado.** Repositório privado no GitHub; a chave do Supabase só no `.env`.

**Treinos #1 a #5** (17:59 a 18:56): imitação pura das suas gravações, de 24 mil
a 47 mil quadros.

## 2. A mosca aprende de verdade (13/10, noite)

| Hora | O que mudou |
|---|---|
| 18:27 | Primeiro commit: painel, mosca 3D, imitação e Supabase |
| 18:37 | **Fase 2:** a imitação passa a pesar mais o que deu certo (recompensa) |
| 18:42 | `comparar.py`: compara versões pelas partidas registradas |
| 18:56 | **Fase 3:** olho novo (visão periférica + fóvea + memória de ~0,15 s) |
| 19:12 | Reflexo de sair do lugar: parada demais, ela tenta andar ou pular |
| 19:39 | **Fase 4:** aprende jogando, com o **torneio campeã x desafiante** |
| 19:57 | Ataque em toques repetidos e Foco segurado 1,5 s (ela não conseguia curar) |
| 20:04 | Morte no HUD, torneio estatístico e testes automáticos |
| 20:08 | Medida de melhoria: "de X para Y houve W%" |
| 21:16 | **Fase 5:** o cérebro com a **fiação real da mosca** (conectoma FlyWire) |
| 21:30 | Exploração: Tab, hábito de olhar o mapa e prêmio por sala nova |
| 21:38 | Detector de **presa** (forçando parede, pulando onde não alcança) |
| 21:45 | Treino com peso pela vantagem (AWR) e cache do olho |
| 22:55 | Detector de **loop** (andando em círculos) |
| 23:02 | Painel de **evolução** (`evolucao.py`) |
| 23:11 | Tudo abre com um clique ou **Ctrl+Alt+M** |

**O torneio** nasceu de uma regra sua: *"se tem chance de piora, não faça"*. Todo
treino gera uma **desafiante**; a **campeã** só é trocada se a desafiante jogar
comprovadamente melhor, em rodadas alternadas de 1 minuto, com margem
estatística. Assim a mosca aprende sozinha sem nunca piorar quem está jogando.

**Os dois cérebros** passaram a se revezar: a rede inventada ("mlp") e o
conectoma, em que os neurônios e as ligações são os da mosca real e só a força
de cada grupo é aprendida.

**Erros desse período, já corrigidos:**
- Renascer depois de morrer contava como cura (morrer dava prêmio).
- Com o mapa aberto ou em transições, o HUD escurecido virava "morte" falsa
  (uma sessão tinha 29 mortes falsas).
- A mosca ficou viciada em entrar e sair da mesma sala para ganhar "sala nova".

## 3. Primeiras disputas (13/10, noite a 14/10, madrugada)

| Versão | Cérebro | Resultado | Recompensa/min (desafiante × campeã) |
|---|---|---|---|
| #14 | mlp | interrompida (pesos mudaram) | −0,8 × −5,6 (contra #6) |
| **#15** | **conectoma** | **🏆 venceu a #6** | −1,4 × −4,3 (**+67%**) |
| #16 | mlp | perdeu | −2,6 × −2,0 |
| #17 | conectoma | interrompida (gravação nova) | −3,2 × −0,2 |
| #18 | mlp | perdeu | −4,4 × −1,7 |
| #19 | conectoma | interrompida | −3,8 × −2,2 |
| #20 | mlp | perdeu | −3,5 × −2,8 |
| **#21** | **conectoma** | **🏆 venceu a #15** | −2,6 × −4,0 (**+34%**) |
| #22 | conectoma | não disputou (vida lida errada) | — |
| #23 | conectoma | perdeu para a #21 | −13,2 × −5,4 |
| #24 | mlp | em disputa | — |

A #15 foi a **primeira vitória do cérebro real** (conectoma), e a #21 o venceu
de novo: as duas campeãs desde então são da fiação da mosca de verdade.

## 4. Ajustes de comportamento (14/10, 00h–01h)

- **Presa e loop pesam mais** (−0,3 → −0,6) e a meia-volta vem com 4 s
  encostada na parede, antes da punição (6 s).
- **FPS do jogo:** o painel abria 12 threads de contas girando à toa; ficou com
  1, e o treino passou a usar metade dos núcleos, com prioridade baixa.
- **Mapa infinito:** ela abria o mapa e não soltava mais (nas gravações o Tab
  está sempre apertado com o mapa na tela). Agora: no máximo 3 s.
- **Botões inúteis** (Pausar, Reiniciar) saíram; **atalhos** Ctrl+Alt+G
  (gravar) e Ctrl+Alt+C (mosca joga), com o mesmo atalho para parar.
- **Gravação treina na hora** ao parar (antes esperava a disputa acabar).
- **Escalar parede** (Garra de Louva-a-deus) deixou de ser punido como "presa".

## 5. Correção ao vivo e juiz mais justo (14/10, 02h–03h)

- **Correção ao vivo:** com a mosca jogando, é só pegar o teclado quando ela
  errar. Ela solta tudo, o seu trecho é gravado como correção (peso 1,5 no
  treino), e ela volta 2 s depois que você solta. Se ela estava em apuros, a
  ajuda vira um estímulo ruim; toque acidental (< 1 s) é descartado.
- **Regra de perder simétrica:** a desafiante não é mais descartada por azar
  num começo ruim.
- **Dano −2 e morte −8:** antes, ficar parada e andar em círculos puniam mais
  que morrer.

**Erros da leitura pela tela descobertos nessa madrugada:**
- A **máscara tremendo** com 1 de vida virava cura + dano falsos a cada 1–2 s
  (~160 pares em 3 h de gravações). A versão #22 foi treinada com isso e foi
  descartada; o treino agora desfaz essas piscadas.
- O **"+N" do geo** sumindo e o **geo zerado depois de morrer** contavam como
  "pegou geo".
- Com a **janela do jogo em outro tamanho**, a mesma área do mapa virava área
  nova e a memória do mapa não conseguia mais ser salva.
- Pontos verdes no cérebro com o Cavaleiro parado: eram disparos espontâneos
  dos neurônios de recompensa pintados como se fosse prêmio (só desenho).
- Um erro no fim do treino deixou uma desafiante **sem número** e um treino seu
  sem terminar; hoje há um teste que pega esse tipo de erro.

## 6. O juiz de dentro do jogo (14/10, 03h)

Os erros da tela levaram à grande mudança do dia: em vez de adivinhar pela
imagem, perguntar ao próprio jogo.

- A Modding API da comunidade só funciona na versão antiga do jogo (1.5.78); o
  seu é a 1.5.12620 (Unity 6). Em vez de voltar de versão, foi usado o
  **BepInEx** (carregador de mods genérico) com um **plugin próprio**,
  `mod/MoscaEventos`, que manda ao painel 30x/s: sala, posição, velocidade,
  vida, geo, alma, golpes que acertaram e inimigos mortos.
- **A mosca continua vendo só a tela.** O plugin só substitui o juiz.
- **Recompensas exatas e novas:** inimigo morto (+1), sala nova pelo nome real
  (+1, impossível de burlar), lugar novo dentro da sala (+0,2), geo só quando
  sobe, cura só com o Foco.
- **Parada, presa e loop** passaram a vir da posição real do Cavaleiro.
- **O hábito de olhar o mapa** foi desligado: servia só para o painel saber onde
  ela estava, e ela parava de jogar para isso.
- **Gravações guardam o estado do jogo** e a contagem de cada evento com os
  pesos da época: mudar um peso agora vale exato para as gravações já feitas.

Logo na primeira conferência, todas as imagens de dano, morte, cura, golpe e
inimigo morto bateram com o que aconteceu. A tela marcava ~1,5 golpe por minuto;
o plugin mostrou que eram ~13.

---

## O que se aprendeu no caminho

- **Recompensa errada ensina errado, e em silêncio.** Quase todo problema do
  comportamento da mosca veio de um estímulo mal medido, não do cérebro. As
  imagens de `diagnostico/` foram o que revelou cada um.
- **O torneio protegeu a mosca dos próprios erros do projeto.** Versões
  treinadas com dados ruins perderam a disputa e nunca jogaram como campeãs.
- **O cérebro real compete bem.** Das duas trocas de campeã, as duas foram do
  conectoma.

## Próximos passos

1. **Mais dados bons:** deixar a mosca jogar e corrigir ao vivo; gravar lutas e
   exploração (agora premiadas com exatidão).
2. **Memória de alguns segundos:** hoje ela lembra ~0,15 s, e por isso anda em
   círculos e insiste em paredes.
3. **Menos peso às gravações antigas,** julgadas pela tela.
4. **Ajuste fino dos detectores pela posição** com o jogo de verdade.
