# Notas de versão – Leozera

## [v1.0.0] - 2026-04-15

### ✨ Novas funcionalidades

- Implementado modo família completo
- Convite de membros via WhatsApp
- Dashboard compartilhado entre membros

### 💰 Monetização

- Planos individual e família (mensal/anual)
- Integração com Mercado Pago (assinaturas)
- Upgrade via interface

### 🔄 Assinaturas

- Webhook para ativação automática
- Cancelamento com grace period
- Downgrade automático via job

### 📲 Integrações

- Integração com WAHA para envio de mensagens
- Normalização de telefone

### 🎨 UX/UI

- Página de planos reformulada (4 planos)
- Landing page atualizada com plano família
- Sidebar com estados bloqueados melhorados

### 🛠️ Melhorias técnicas

- Centralização de planos (plan_config)
- Validações de acesso por plano
- Tratamento de inconsistências de dados

### 🐛 Correções

- Correção de envio de convite (WAHA / ambiente)
- Ajustes de visual na sidebar

---

## v0.4.1 – Onboarding e Tour do Dashboard

**Versão:** v0.4.1  
**Tipo:** Feature / UX Improvement

### Descrição

* Novo sistema de onboarding completo para novos usuários
* Tour guiado do dashboard implementado
* Checklist inteligente de configuração inicial
* Melhorias na experiência de primeira utilização
* Correção de bugs no posicionamento do tooltip do tour
* Correção da inicialização do tour após carregamento do dashboard

---

## v0.5.0

### ✨ Features

- Sistema de despesas fixas com lembretes automáticos
- Insights financeiros com separação entre global e período
- Novo modelo de resposta da IA (headline + insights)

### 🎨 UX/UI

- Redesign completo do dashboard
- Hierarquia visual aprimorada
- Microinterações e melhorias visuais

### ⚙️ Backend

- Integração de lembretes de despesas no worker Celery
- Controle de envio com `ultimo_envio` (evita duplicações)

### 🐛 Fixes

- Correção de inconsistências de classificação (receita vs despesa)
- Ajustes de responsividade e layout

---

## v0.6.0 – Dashboard Inteligente

### Novas funcionalidades

- Adicionado card de Taxa de Economia
- Implementada barra de Saúde Financeira
- Adicionado indicador de Categoria Dominante com percentual e progress bar
- Implementado alerta automático para categorias acima de 30% dos gastos
- Adicionado card de Conta com Mais Gastos
- Implementado card de tendência de gastos vs mês anterior
- Adicionado indicador Velocidade do Dinheiro
- Melhorada visualização do bloco de Análise Financeira com IA

### Melhorias

- Dashboard agora apresenta métricas financeiras mais claras e visuais
- Melhor experiência de leitura dos dados financeiros
- Estrutura de insights reorganizada (Diagnóstico, Impacto, Projeção, Recomendação)

### Correções

- Correção de exibição de horário das transações (timezone Brasil)
- Correção de layout no gráfico Receita vs Despesa
