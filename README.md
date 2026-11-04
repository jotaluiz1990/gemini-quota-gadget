# ⚡ Gemini Quota Gadget

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue?logo=windows)](https://microsoft.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen?logo=python)](https://python.org)
[![UI](https://img.shields.io/badge/GUI-CustomTkinter%20%2B%20DWM-informational)](https://github.com/TomSchimansky/CustomTkinter)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Widget flutuante moderno para desktop que monitora em tempo real suas cotas de uso de IA no **Google Antigravity IDE** e no **Google Gemini Web (PRO / Advanced)**, com contagem regressiva de reset, estimativas preditivas inteligentes offline e login integrado com 1 clique.

---

## 🌟 Principais Recursos

- 🪟 **Interface Flutuante Moderna (Estilo Gadget)**:
  - Sem bordas feias de janela (*frameless*), com **cantos arredondados nativos do Windows 11** via API DWM e chave de transparência.
  - Fixada no topo (*topmost* opcional) e arrastável clicando e movendo a partir de qualquer ponto do fundo ou da barra superior.
  - **Redimensionável**: puxe com o mouse pela alça visual `◿` no canto inferior direito ou pelas bordas.
  - **Scroll inteligente**: barra de rolagem oculta automaticamente quando todo o conteúdo cabe na tela.

- ⚡ **Zero-Flicker & Atualizações em Tempo Real**:
  - Consulta automática em background a cada 30 segundos (ou instantaneamente pelo botão `↻`).
  - Atualização in-place dos widgets existentes: a janela **não pisca**, não recria componentes e não consome recursos desnecessários.

- ⏱️ **Monitoramento Detalhado de Cotas**:
  - **Modelos do Antigravity IDE**: Exibe cotas de limite semanal e limite de 5 horas para `Gemini Models` (Flash e Pro), `Gemini 4 Argon` e `Claude/GPT models`.
  - **Contagem Regressiva e Data/Hora de Reset**: Mostra exatamente quando cada cota será restabelecida (ex: `⏱ Reseta em 2h 29m • 02/11 às 20:21`).
  - **Google Gemini Web (PRO)**: Monitora tanto o **Uso Atual** quanto o **Limite Semanal** da interface web oficial.

- 🔮 **Modo Inteligente Offline & Dados Previstos (Estimado)**:
  - Salva a última leitura válida ao fechar ou ao desconectar.
  - Se o Antigravity ou a Web estiverem offline, exibe os últimos dados conhecidos em um elegante **cartão âmbar/amarelo com o selo `⚠ ESTIMADO`**.
  - **Previsão Automática de Reset**: Quando o horário programado de reset chega (mesmo com o Antigravity offline), o gadget restaura automaticamente a cota prevista para **100% restante** e projeta o próximo ciclo (ex: `+5h` para limite de 5 horas ou `+7 dias` para limites semanais), informando que a cota foi restaurada.

- 🤫 **Operação 100% Silenciosa (Zero Popups)**:
  - Todas as chamadas de descoberta e verificação em segundo plano utilizam flags do kernel (`CREATE_NO_WINDOW` e `SW_HIDE`), impedindo qualquer janela de CMD ou PowerShell de piscar na sua tela.

- 🌐 **Sessão Permanente do Gemini Web com Renovação Silenciosa Contínua**:
  - Faça login uma **única vez** através da janela nativa do Edge WebView2.
  - A sessão fica salva de forma persistente e segura no disco (`.gemini_session`).
  - O gadget rastreia dinamicamente a rotação de cookies (`__Secure-1PSIDTS`) pelas respostas HTTP e conta com **auto-renovação silenciosa em segundo plano** (`hidden=True`, zero janelas, zero popups). Você nunca mais precisará ficar reconectando manualmente!

- 📌 **Bandeja do Sistema (System Tray) & Sem Ícone na Barra de Tarefas**:
  - Utiliza estilo nativo `WS_EX_TOOLWINDOW` do Windows para não poluir sua barra de tarefas nem a listagem do Alt+Tab.
  - Fica acessível discretamente na bandeja do sistema (ao lado do relógio do Windows).
  - Menu da bandeja com opções de: *Mostrar Widget*, *Configurações*, *Atualizar Agora* e *Sair*.
  - **Iniciar com o Windows**: Chave de alternância no menu de configurações para habilitar inicialização automática no Registro do Windows (`HKCU\...\Run`).
  - Lembra com precisão a **posição (x, y)** e o **tamanho (largura, altura)** mesmo em setups com múltiplos monitores.

---

## 🚀 Como Usar

### Opção 1: Executável Pronto (Sem instalar Python)
1. Acesse a pasta `dist/` deste repositório ou baixe a versão compilada em **Releases**.
2. Execute o arquivo **`GeminiQuotaGadget.exe`**.
3. O gadget abrirá diretamente no canto da sua tela!

### Opção 2: Executando via Código Fonte Python
1. Certifique-se de ter o Python 3.10 ou superior instalado no Windows.
2. Clone este repositório:
   ```bash
   git clone https://github.com/jotaluiz1990/gemini-quota-gadget.git
   cd gemini-quota-gadget
   ```
3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
4. Execute o aplicativo:
   ```bash
   python main.py
   ```
   *(ou dê um duplo clique para iniciar sem janela de terminal através de `pythonw main.py`)*

---

## ⚙️ Configuração das Cotas

Abra o menu de configurações clicando no ícone de engrenagem (**⚙**) no topo do widget:

1. **Modelos do Antigravity (IDE)**:
   - Marque ou desmarque os grupos de modelos que deseja visualizar (`Gemini Models`, `Gemini 4 Argon`, `Claude and GPT models`).
2. **Google Gemini Web (PRO)**:
   - Marque a caixa *Ativar Monitoramento do Gemini Web (PRO)*.
   - Clique em **🌐 Fazer Login no Gemini (Captura Automática)**.
   - Uma janela de navegador seguro será aberta para autenticação na sua conta Google. Assim que você entrar, a janela fecha sozinha e os limites de uso passam a ser monitorados!
3. **Aparência e Visualização**:
   - **Tamanho da Fonte**: Selecione entre `Pequeno`, `Médio` ou `Grande`.
   - **Opacidade da Janela**: Ajuste o slider para ver a janela se tornar translúcida na hora (ao vivo).
   - **Modo de Exibição das Cotas**: Selecione `% Restante` ou `% Consumida`.
4. **Sistema e Inicialização**:
   - Ative a opção *Iniciar automaticamente com o Windows* para o gadget carregar pronto sempre que você ligar o computador.

---

## 🛠️ Como Compilar o Executável Standalone

Para gerar o arquivo `.exe` portátil de arquivo único (`--onefile`) sem console (`--noconsole`):

Basta dar um duplo clique no script:
```cmd
build.bat
```

Ou rodar manualmente via terminal:
```cmd
python -m PyInstaller --noconsole --onefile --clean --name "GeminiQuotaGadget" --collect-all "webview" --hidden-import "pystray" --hidden-import "PIL" --hidden-import "gemini_web_client" --hidden-import "gemini_login_window" main.py
```

O executável final será gerado em:
```
dist/GeminiQuotaGadget.exe
```

---

## 📁 Estrutura do Projeto

```text
├── main.py                  # Aplicação principal (GUI CustomTkinter, lógica de drag/resize, DWM e polling)
├── gemini_web_client.py     # Cliente HTTP/RPC reverso para consulta de cotas de gemini.google.com
├── gemini_login_window.py   # Módulo WebView2 nativo para login e captura automática de cookies
├── quota_data.json          # Arquivo de persistência de configurações, posições e última leitura
├── build.bat                # Script de compilação automatizada com PyInstaller
├── requirements.txt         # Lista de dependências Python
└── README.md                # Documentação oficial do projeto
```

---

## 🛡️ Privacidade e Segurança

- Todo o processamento é executado **estritamente de forma local** no seu computador.
- As consultas ao Antigravity ocorrem diretamente no loopback local (`http://127.0.0.1:[porta]`) via token CSRF gerado pela própria IDE.
- Os cookies do Gemini Web são armazenados apenas no arquivo local `quota_data.json` na sua própria máquina e utilizados exclusivamente para consultar seus limites de uso.

---

## 📄 Licença

Distribuído sob a licença MIT. Consulte `LICENSE` para obter mais detalhes.
