# GCodePen

Texto → G-code para plotter de caneta com GRBL. Só usa padrões do GRBL: `G21 G90 G17 G94` + `G0/G1` (nenhum `$xx=`).
A caneta é controlada de um destes modos (toggle em **Caneta**):
- **Eixo Z** — Z mín = caneta escreve, Z máx = levantada.
- **Servo (PWM do spindle)** — `M3 S<levantada>` / `M3 S<no papel>` + `G4` de espera; não usa Z. Requer `$32=0` (modo laser desligado)
  e `S` ≤ `$30`. O G-code termina com a caneta levantada, sem `M5` (para não soltar o servo).

## Instalação
```bash
sudo usermod -aG dialout $USER   # acesso à porta serial no Linux (relogar depois)
./run.sh serve                   # na 1ª execução cria a .venv e instala o requirements.txt
```
(Manual: `python -m venv --system-site-packages .venv && .venv/bin/pip install -r requirements.txt`)

## Scripts
- `./run.sh <args>` — wrapper de `.venv/bin/python -m gcodepen <args>`; funciona de qualquer diretório.
- `./kill.sh` — encerra o servidor GCodePen, em qualquer porta.

## Interface web
```bash
export GEMINI_API_KEY=...   # opcional: habilita 🎤 Falar e ✏️ Desenhar (modelo: GEMINI_MODEL, padrão gemini-flash-latest)
./run.sh serve --port 8000     # http://127.0.0.1:8000 (só localhost); ./kill.sh para parar
```
Texto + fonte (Hershey de traço único, ou TTF/OTF do sistema), preview, G-code, PDF (texto por página),
voz→texto, desenho por IA (experimental) e painel **Máquina**: conectar, jog, zerar, caneta ↑/↓,
enviar G-code com controle de buffer (character-counting), pausar/continuar/parar, console.

**Folha / espaço de trabalho**
- **Quadrante** (1º–4º; padrão **4º: X+ e Y−**, origem no canto superior esquerdo da folha): o texto cresce para X+ e as linhas descem em Y−.
- **Curso máx. X / Y**: o texto quebra sozinho, em função do tamanho da fonte, para caber nesse curso (preenchido com `$130/$131`
  ao conectar). "Largura da área" preenchida substitui a quebra automática. Se o texto passar do curso em altura, aparece um aviso.
- **Rotação da folha** (°, anti-horário; botões ↺ ↻ de 90°): o texto corre ao longo de Y e a quebra passa a usar o curso Y.
- **Margem**: distância à origem e à borda oposta do curso.

**Velocidade** (aba): avanço de escrita, de deslocamento com a caneta levantada (vazio = `G0` na velocidade máxima; preenchido =
`G1 F…`) e de descida do Z. O aviso de avanço alto e a estimativa de tempo usam `$110/$111` da placa quando conectada.

**Perfis** (aba): todas as configurações (menos o texto) são salvas sozinhas ~0,6 s após qualquer mudança e voltam ao abrir.
Também dá para salvar, carregar e excluir perfis nomeados, ou restaurar os padrões. Ficam em
`~/.config/gcodepen/profiles.json` (ou `$XDG_CONFIG_HOME/gcodepen/…`; `GCODEPEN_CONFIG=/caminho.json` troca o arquivo).

**Jog**: tocar = 1 passo; segurar (> 250 ms) = movimento contínuo no avanço do jog (vários `$J=` curtos, sem esperar o passo
terminar); soltar manda o jog-cancel (`0x85`) e a máquina freia. Se o navegador sumir, o servidor para sozinho em < 1 s.

## CLI
```bash
./run.sh text "Olá, mundo" --font futural --size 8 --zmin -1 --zmax 3 -o saida.gcode
./run.sh text "Olá" --pen servo --pen-up 700 --pen-down 300 --quadrant 4 --travel-x 200 --travel-y 280 --rotate 90
./run.sh text --pdf doc.pdf --page 1 --width 180 -o p1.gcode
```

## Primeiro teste na máquina
1. Conecte, destrave (`$X`) ou faça home (`$H`), leve a caneta ao canto de origem do papel (no 4º quadrante, o canto superior esquerdo) e clique **Zerar XY**.
2. (Modo Z) ajuste o Z com o jog até a ponta tocar levemente o papel: esse é o seu **Z mín**; um pouco acima, **Z máx**.
   (No modo servo, ajuste os valores de S até a ponta tocar / ficar acima do papel.) (Os Z da UI são em coordenadas de trabalho — use **Zerar Z** num ponto de referência conhecido.)
3. Primeiro rode **sem caneta / com Z alto**, confira o movimento; depois escreva.

## Testes
`.venv/bin/python -m pytest`
