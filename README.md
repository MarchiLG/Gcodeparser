# GCodePen

Texto → G-code para plotter de caneta com GRBL. **Z mín = caneta escreve, Z máx = caneta levantada.**
Só usa padrões do GRBL: `G21 G90 G17 G94` + `G0/G1` (nenhum `$xx=`, nenhum `M3/M5`).

## Instalação
```bash
python -m venv --system-site-packages .venv && .venv/bin/pip install -r requirements.txt
sudo usermod -aG dialout $USER   # acesso à porta serial no Linux (relogar depois)
```

## Interface web
```bash
export GEMINI_API_KEY=...   # opcional: habilita 🎤 Falar e ✏️ Desenhar (modelo: GEMINI_MODEL, padrão gemini-flash-latest)
.venv/bin/python -m gcodepen serve --port 8000     # http://127.0.0.1:8000 (só localhost)
```
Texto + fonte (Hershey de traço único, ou TTF/OTF do sistema), preview, G-code, PDF (texto por página),
voz→texto, desenho por IA (experimental) e painel **Máquina**: conectar, jog, zerar, caneta ↑/↓,
enviar G-code com controle de buffer (character-counting), pausar/continuar/parar, console.

## CLI
```bash
.venv/bin/python -m gcodepen text "Olá, mundo" --font futural --size 8 --zmin -1 --zmax 3 -o saida.gcode
.venv/bin/python -m gcodepen text --pdf doc.pdf --page 1 --width 180 -o p1.gcode
```

## Primeiro teste na máquina
1. Conecte, destrave (`$X`) ou faça home (`$H`), leve a caneta à origem do papel e clique **Zerar XY**.
2. Ajuste o Z com o jog até a ponta tocar levemente o papel: esse é o seu **Z mín**; um pouco acima, **Z máx**.
   (Os Z da UI são em coordenadas de trabalho — use **Zerar Z** num ponto de referência conhecido.)
3. Primeiro rode **sem caneta / com Z alto**, confira o movimento; depois escreva.

## Testes
`.venv/bin/python -m pytest`
