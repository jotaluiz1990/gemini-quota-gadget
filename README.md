# ⚡ Gemini Quota Gadget

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue?logo=windows)](https://microsoft.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen?logo=python)](https://python.org)
[![UI](https://img.shields.io/badge/GUI-CustomTkinter%20%2B%20DWM-informational)](https://github.com/TomSchimansky/CustomTkinter)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Widget flutuante moderno para desktop que monitora em tempo real suas cotas de uso de IA no **Google Antigravity IDE** e no **Google Gemini Web (PRO / Advanced)**, com contagem regressiva de reset, estimativas preditivas inteligentes offline, login integrado com 1 clique e controle estético completo.

---

## 🌟 Principais Recursos

- 🪟 **Interface Flutuante Moderna (Estilo Gadget)**:
  - Sem bordas de janela (*frameless*), com **cantos arredondados nativos do Windows 11** via API DWM e chave de transparência.
  - Fixada no topo (*topmost* opcional) e arrastável clicando e movendo a partir de qualquer ponto do fundo ou da barra superior.
  - **Redimensionável com o mouse**: puxe pela alça visual `◿` no canto inferior direito ou pelas bordas da janela.
  - **Scroll inteligente**: a barra de rolagem lateral se oculta automaticamente quando todo o conteúdo cabe na tela.

- ⚡ **Zero-Flicker & Atualizações em Tempo Real**:
  - Consulta automática em background a cada 30 segundos (ou instantaneamente pelo botão `↻`).
  - Atualização in-place dos widgets existentes: a janela **não pisca**, não recria componentes e não consome recursos desnecessários.

- ⏱️ **Monitoramento Detalhado de Cotas**:
  - **Modelos do Antigravity IDE**: Exibe cotas de limite semanal e limite de 5 horas para `Gemini Models` (Flash e Pro), `Gemini 4 Argon` e `Claude/GPT models`.
  - **Contagem Regressiva e Data/Hora de Reset**: Mostra exatamente quando cada cota será restabelecida (ex: `⏱ Reseta em 2h 29m • 04/11 às 20:21`).
  - **Google Gemini Web (PRO)**: Monitora tanto o **Uso Atual** quanto o **Limite Semanal** da interface web oficial.

- 🔮 **Modo Inteligente Offline & Dados Previstos (Estimado)**:
  - Salva a última leitura válida ao fechar ou ao desconectar.
  - Se o Antigravity ou a Web estiverem offline, exibe os últimos dados conhecidos em um elegante **cartão âmbar/amarelo com o selo `⚠ ESTIMADO`**.
  - **Previsão Automática de Reset**: Quando o horário programado de reset chega (mesmo com o Antigravity offline), o gadget restaura automaticamente a cota prevista para **100% restante** e projeta o próximo ciclo (ex: `+5h` para limite de 5 horas ou `+7 dias` para limites semanais), informando que a cota foi restaurada.

- 🎨 **Personalização Visual e Controle Total**:
  - **Tamanho da Fonte Customizável**: Alterne entre `Pequeno` (compacto), `Médio` (padrão ampliado para leitura confortável) e `Grande` (ideal para monitores de alta resolução).
  - **Opacidade do Fundo com Preview em Tempo Real**: Ajuste o controle deslizante de 40% a 100% de transparência para integrar o gadget perfeitamente ao seu papel de parede.
  - **Modo de Exibição das Porcentagens**: Escolha visualizar suas cotas como **% Restante** (quanto ainda tem) ou **% Consumida** (quanto já gastou), com adaptação dinâmica das cores das barras de progresso.

- 🌐 **Sessão Permanente do Gemini Web com Auto-Renovação Silenciosa**:
  - Faça login uma **única vez** através da janela nativa do Microsoft Edge WebView2 com suporte a contas Google e 2FA.
  - A sessão fica salva de forma persistente e segura no disco (`.gemini_session`).
  - O gadget rastreia dinamicamente a rotação de cookies (`__Secure-1PSIDTS`) pelas respostas HTTP e conta com **auto-renovação silenciosa em segundo plano** (`hidden=True`, zero janelas, zero popups). Você nunca mais precisará ficar reconectando manualmente!

- 🤫 **Operação 100% Silenciosa (Zero Popups)**:
  - Todas as chamadas de descoberta e verificação em segundo plano utilizam flags do kernel (`CREATE_NO_WINDOW` e `SW_HIDE`), impedindo qualquer janela de CMD ou terminal de piscar na sua tela.

- 📌 **Bandeja do Sistema (System Tray) & Sem Ícone na Barra de Tarefas**:
  - Utiliza o estilo nativo `WS_EX_TOOLWINDOW` do Windows para não poluir sua barra de tarefas nem a listagem do Alt+Tab.
  - Fica acessível discretamente na bandeja do sistema (ao lado do relógio do Windows).
  - Menu da bandeja com opções de: *Mostrar Widget*, *Configurações*, *Atualizar Agora* e *Sair*.
  - **Iniciar com o Windows**: Chave de alternância no menu de configurações para habilitar inicialização automática no Registro do Windows (`HKCU\...\Run`).
  - Lembra com precisão a **posição (x, y)** e o **tamanho (largura, altura)** mesmo em setups com múltiplos monitores.

---

## 🚀 Como Usar

### Opção 1: Executável Standalone Portátil (Recomendado)
Ideal tanto para seu computador pessoal quanto para o **PC do trabalho** (não precisa de Python nem permissões de administrador):
1. Baixe o arquivo **`GeminiQuotaGadget.exe`** da pasta `dist/` ou da seção de **Releases**.
2. Coloque-o em qualquer pasta local (ex: `C:\Ferramentas\GeminiQuotaGadget` ou na pasta de Documentos).
3. Dê um duplo clique para abrir: o gadget iniciará no cantinho da tela pronto para uso!

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
   *(ou use `pythonw main.py` para iniciar sem janela de terminal)*

---

## ⚙️ Configurações do Gadget

Abra o menu de configurações clicando no ícone de engrenagem (**⚙**) no topo do widget:

1. **Modelos do Antigravity (IDE)**:
   - Marque ou desmarque os grupos de modelos que deseja visualizar (`Gemini Models`, `Gemini 4 Argon`, `Claude and GPT models`).
2. **Google Gemini Web (PRO)**:
   - Marque a caixa *Ativar Monitoramento do Gemini Web (PRO)*.
   - Clique em **🌐 Fazer Login no Gemini (Captura Automática)** (ou *🔄 Reconectar / Trocar de Conta Google*).
   - Uma janela de navegador seguro será aberta para autenticação na sua conta Google. Assim que você entrar, a janela fecha sozinha e os limites de uso passam a ser monitorados continuamente!
3. **Aparência e Visualização**:
   - **Tamanho da Fonte**: Alterne entre `Pequeno`, `Médio` ou `Grande`.
   - **Opacidade da Janela**: Ajuste o slider para ver a janela se tornar translúcida na hora (ao vivo).
   - **Modo de Exibição das Cotas**: Selecione entre `% Restante` ou `% Consumida`.
4. **Sistema e Inicialização**:
   - Ative a opção *Iniciar automaticamente com o Windows* para o gadget carregar pronto sempre que você ligar o computador.

---

## 🛠️ Como Compilar o Executável

Para gerar o arquivo `.exe` portátil de arquivo único (`--onefile`) sem console (`--noconsole`):

Basta dar um duplo clique no script:
```cmd
build.bat
```

Ou executar manualmente via terminal:
```cmd
python -m PyInstaller ^
    --noconsole ^
    --onefile ^
    --clean ^
    --name "GeminiQuotaGadget" ^
    --collect-all "webview" ^
    --hidden-import "pystray" ^
    --hidden-import "PIL" ^
    --hidden-import "gemini_web_client" ^
    --hidden-import "gemini_login_window" ^
    --hidden-import "clr_loader" ^
    --hidden-import "pythonnet" ^
    main.py
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
├── gemini_login_window.py   # Módulo WebView2 nativo para login e auto-renovação silenciosa de cookies
├── quota_data.json          # Arquivo de persistência de configurações, posições e última leitura
├── build.bat                # Script de compilação automatizada com PyInstaller
├── requirements.txt         # Lista de dependências Python
└── README.md                # Documentação oficial do projeto
```

---

## 🛡️ Privacidade e Segurança

- Todo o processamento é executado **estritamente de forma local** no seu computador.
- As consultas ao Antigravity ocorrem diretamente no loopback local (`http://127.0.0.1:[porta]`) via token CSRF gerado pela própria IDE.
- Os dados do Gemini Web ficam salvos de forma isolada na sua própria máquina (`.gemini_session` e `quota_data.json`), sem envio para servidores externos.

---

## 📄 Licença

Distribuído sob a licença MIT. Consulte `LICENSE` para obter mais detalhes.
