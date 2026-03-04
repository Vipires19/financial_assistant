/**
 * Agenda JavaScript - FullCalendar Integration
 * Gerencia eventos de compromissos com interações AJAX
 */

const API_BASE = '/finance/api';

// Objeto principal do calendário
const calendario = {
    calendar: null,
    compromissoAtual: null,
    viewType: 'dayGridMonth',
    
    init() {
        const calendarEl = document.getElementById('agenda-calendar') || document.getElementById('calendar');
        if (!calendarEl) {
            console.error('Elemento #agenda-calendar não encontrado');
            return;
        }

        const viewBtns = document.querySelectorAll('.agenda-view-btn');
        const activeBtn = document.querySelector('.agenda-view-btn.active');
        this.viewType = (activeBtn && activeBtn.dataset.view) || 'dayGridMonth';

        // Controle único: sem toolbar do FullCalendar; apenas botões custom (Dia, Semana, Mês, + Novo)
        const calendarConfig = {
            initialView: this.viewType,
            locale: 'pt-br',
            allDaySlot: false,
            headerToolbar: false,
            editable: true,
            selectable: true,
            nowIndicator: true,
            slotMinTime: '00:00:00',
            slotMaxTime: '24:00:00',
            expandRows: true,
            height: 'auto',
            dayMaxEvents: true,
            slotLabelFormat: {
                hour: '2-digit',
                minute: '2-digit',
                hour12: false
            },
            eventTimeFormat: {
                hour: '2-digit',
                minute: '2-digit',
                hour12: false
            },
            dayHeaderFormat: {
                weekday: 'short',
                day: '2-digit',
                month: '2-digit'
            },
            views: {
                timeGridWeek: {
                    slotDuration: '00:30:00'
                },
                timeGridDay: {
                    slotDuration: '00:30:00'
                },
                dayGridMonth: {
                    dayMaxEventRows: 3
                }
            },
            select: this.onSelect.bind(this),
            dateClick: this.onDateClick.bind(this),
            eventClick: this.onEventClick.bind(this),
            eventDrop: this.onEventDrop.bind(this),
            events: this.fetchEvents.bind(this),
            eventClassNames: (arg) => [arg.event.extendedProps?.status || 'pendente'],
            eventContent: function(arg) {
                const title = arg.event.title || '';
                const titleEscaped = title.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                return {
                    html: '<div class="fc-event-modern"><div class="fc-event-title" title="' + titleEscaped + '">' + (title || '') + '</div><div class="fc-event-time">' + (arg.timeText || '') + '</div></div>'
                };
            },
            viewDidMount: (view) => {
                this.viewType = view.type;
                this.updateTitle();
                viewBtns.forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.view === view.type);
                });
            }
        };

        this.calendar = new FullCalendar.Calendar(calendarEl, calendarConfig);
        calendarEl.style.minHeight = '400px';
        this.calendar.render();
        this.updateTitle();

        setTimeout(() => {
            if (this.calendar) this.calendar.updateSize();
        }, 300);

        // + Novo: abre o modal existente (criar compromisso)
        const addBtn = document.getElementById('addCompromissoBtn');
        if (addBtn) addBtn.addEventListener('click', () => this.abrirModal());
        const closeBtn = document.getElementById('closeModal');
        if (closeBtn) closeBtn.addEventListener('click', () => this.fecharModal());
        const cancelBtn = document.getElementById('cancelBtn');
        if (cancelBtn) cancelBtn.addEventListener('click', () => this.fecharModal());
        const modalOverlay = document.getElementById('compromissoModal');
        if (modalOverlay) {
            modalOverlay.addEventListener('click', (e) => {
                if (e.target === modalOverlay) this.fecharModal();
            });
        }
        const formEl = document.getElementById('compromissoForm');
        if (formEl) formEl.addEventListener('submit', (e) => {
            e.preventDefault();
            this.salvarCompromisso();
        });
        const deleteBtn = document.getElementById('deleteBtn');
        if (deleteBtn) deleteBtn.addEventListener('click', () => this.excluirCompromisso());

        // Botões custom: Dia → timeGridDay, Semana → timeGridWeek, Mês → dayGridMonth
        viewBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const view = btn.dataset.view;
                if (view && this.calendar) {
                    this.calendar.changeView(view);
                    this.updateTitle();
                    setTimeout(() => { if (this.calendar) this.calendar.updateSize(); }, 200);
                }
            });
        });

        const prevBtn = document.getElementById('agendaPrev');
        const nextBtn = document.getElementById('agendaNext');
        const todayBtn = document.getElementById('agendaToday');
        if (prevBtn) prevBtn.addEventListener('click', () => { this.calendar.prev(); this.updateTitle(); });
        if (nextBtn) nextBtn.addEventListener('click', () => { this.calendar.next(); this.updateTitle(); });
        if (todayBtn) todayBtn.addEventListener('click', () => { this.calendar.today(); this.updateTitle(); });

        window.addEventListener('resize', () => {
            if (this.calendar) this.calendar.updateSize();
        });
    },

    updateTitle() {
        const el = document.getElementById('agendaTitleDate');
        if (!el || !this.calendar) return;
        const view = this.calendar.view;
        if (view && view.title) el.textContent = view.title;
    },
    
    fetchEvents(info, successCallback, failureCallback) {
        const start = info.startStr;
        const end = info.endStr;
        
        fetch(`${API_BASE}/agenda/?start=${start}&end=${end}`)
            .then(response => response.json())
            .then(data => {
                successCallback(data);
            })
            .catch(error => {
                console.error('Erro ao buscar compromissos:', error);
                failureCallback(error);
            });
    },
    
    onSelect(selectInfo) {
        // Quando o usuário seleciona um intervalo de datas (arrasta no calendário)
        const start = selectInfo.start;
        const end = selectInfo.end || new Date(start.getTime() + 60 * 60 * 1000);
        const data = start.toISOString().split('T')[0];
        const hora = start.toTimeString().split(' ')[0].substring(0, 5);
        const hora_fim = end.toTimeString().split(' ')[0].substring(0, 5);
        this.abrirModal();
        const dataEl = document.getElementById('data');
        const horaEl = document.getElementById('hora');
        const horaFimEl = document.getElementById('hora_fim');
        if (dataEl) dataEl.value = data;
        if (horaEl) horaEl.value = hora;
        if (horaFimEl) horaFimEl.value = hora_fim;
    },

    onDateClick(dateClickInfo) {
        // Quando o usuário clica em um horário (abre modal com essa data/hora)
        const start = dateClickInfo.date;
        const end = new Date(start.getTime() + 60 * 60 * 1000);
        const data = start.toISOString().split('T')[0];
        const hora = start.toTimeString().split(' ')[0].substring(0, 5);
        const hora_fim = end.toTimeString().split(' ')[0].substring(0, 5);
        this.abrirModal();
        const dataEl = document.getElementById('data');
        const horaEl = document.getElementById('hora');
        const horaFimEl = document.getElementById('hora_fim');
        if (dataEl) dataEl.value = data;
        if (horaEl) horaEl.value = hora;
        if (horaFimEl) horaFimEl.value = hora_fim;
    },
    
    onEventClick(clickInfo) {
        // Quando o usuário clica em um evento
        const evento = clickInfo.event;
        const compromissoId = evento.id;
        
        this.carregarCompromisso(compromissoId);
    },
    
    onEventDrop(dropInfo) {
        // Quando o usuário arrasta um evento para outra data/hora
        const evento = dropInfo.event;
        const start = evento.start;
        const data = start.toISOString().split('T')[0];
        const hora = start.toTimeString().split(' ')[0].substring(0, 5);
        
        this.atualizarDataHora(evento.id, data, hora);
    },
    
    async carregarCompromisso(compromissoId) {
        try {
            // Buscar compromisso via API
            const response = await fetch(`${API_BASE}/agenda/?start=2000-01-01&end=2100-12-31`);
            const eventos = await response.json();
            const evento = eventos.find(e => e.id === compromissoId);
            
            if (!evento) {
                alert('Compromisso não encontrado');
                return;
            }
            
            // Extrair data e hora do evento
            const start = new Date(evento.start);
            const end = evento.end ? new Date(evento.end) : new Date(start.getTime() + 60 * 60 * 1000);
            const data = start.toISOString().split('T')[0];
            const hora = start.toTimeString().split(' ')[0].substring(0, 5);
            const hora_fim = end.toTimeString().split(' ')[0].substring(0, 5);
            
            // Preencher formulário
            document.getElementById('compromissoId').value = compromissoId;
            document.getElementById('titulo').value = evento.title;
            document.getElementById('descricao').value = evento.description || '';
            document.getElementById('data').value = data;
            document.getElementById('hora').value = hora;
            document.getElementById('hora_fim').value = hora_fim;
            document.getElementById('tipo').value = evento.extendedProps?.tipo || '';
            document.getElementById('status').value = evento.extendedProps?.status || 'pendente';
            
            document.getElementById('modalTitle').textContent = 'Editar Compromisso';
            document.getElementById('deleteBtn').classList.remove('hidden');
            
            this.compromissoAtual = compromissoId;
            this.abrirModal();
            
        } catch (error) {
            console.error('Erro ao carregar compromisso:', error);
            alert('Erro ao carregar compromisso');
        }
    },
    
    async salvarCompromisso() {
        const compromissoId = document.getElementById('compromissoId').value;
        const titulo = document.getElementById('titulo').value.trim();
        const descricao = document.getElementById('descricao').value.trim();
        const data = document.getElementById('data').value;
        const hora = document.getElementById('hora').value;
        const hora_fim = document.getElementById('hora_fim').value;
        const tipo = document.getElementById('tipo').value;
        const status = document.getElementById('status').value;
        
        if (!titulo || !data || !hora || !hora_fim) {
            alert('Por favor, preencha todos os campos obrigatórios');
            return;
        }
        
        // Validar que hora_fim é posterior a hora
        if (hora_fim <= hora) {
            alert('O horário de término deve ser posterior ao horário de início');
            return;
        }
        
        try {
            let response;
            
            if (compromissoId) {
                // Atualizar compromisso existente
                response = await fetch(`${API_BASE}/compromissos/${compromissoId}/update/`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    },
                    body: JSON.stringify({
                        titulo,
                        descricao,
                        data,
                        hora,
                        hora_fim,
                        tipo,
                        status
                    })
                });
            } else {
                // Criar novo compromisso
                response = await fetch(`${API_BASE}/compromissos/create/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    },
                    body: JSON.stringify({
                        titulo,
                        descricao,
                        data,
                        hora,
                        hora_fim,
                        tipo
                    })
                });
            }
            
            const result = await response.json();
            
            if (result.success || response.ok) {
                alert(result.message || 'Compromisso salvo com sucesso!');
                this.fecharModal();
                this.calendar.refetchEvents();
            } else {
                alert(result.error || 'Erro ao salvar compromisso');
            }
            
        } catch (error) {
            console.error('Erro ao salvar compromisso:', error);
            alert('Erro ao salvar compromisso');
        }
    },
    
    async atualizarDataHora(compromissoId, data, hora) {
        try {
            const response = await fetch(`${API_BASE}/compromissos/${compromissoId}/update/`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    data,
                    hora
                })
            });
            
            const result = await response.json();
            
            if (!result.success && !response.ok) {
                // Reverter mudança se falhar
                this.calendar.refetchEvents();
                alert('Erro ao atualizar data/hora do compromisso');
            }
            
        } catch (error) {
            console.error('Erro ao atualizar data/hora:', error);
            this.calendar.refetchEvents();
            alert('Erro ao atualizar data/hora do compromisso');
        }
    },
    
    async excluirCompromisso() {
        const compromissoId = document.getElementById('compromissoId').value;
        
        if (!compromissoId) {
            return;
        }
        
        if (!confirm('Tem certeza que deseja excluir este compromisso?')) {
            return;
        }
        
        try {
            const response = await fetch(`${API_BASE}/compromissos/${compromissoId}/delete/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.getCsrfToken()
                }
            });
            
            const result = await response.json();
            
            if (result.success || response.ok) {
                alert('Compromisso excluído com sucesso!');
                this.fecharModal();
                this.calendar.refetchEvents();
            } else {
                alert(result.error || 'Erro ao excluir compromisso');
            }
            
        } catch (error) {
            console.error('Erro ao excluir compromisso:', error);
            alert('Erro ao excluir compromisso');
        }
    },
    
    abrirModal() {
        const modal = document.getElementById('compromissoModal');
        if (modal) modal.classList.add('show');
    },

    fecharModal() {
        const modal = document.getElementById('compromissoModal');
        if (modal) modal.classList.remove('show');
        const form = document.getElementById('compromissoForm');
        if (form) form.reset();
        const idEl = document.getElementById('compromissoId');
        if (idEl) idEl.value = '';
        const titleEl = document.getElementById('modalTitle');
        if (titleEl) titleEl.textContent = 'Novo Compromisso';
        const delBtn = document.getElementById('deleteBtn');
        if (delBtn) delBtn.classList.add('hidden');
        this.compromissoAtual = null;
    },
    
    getCsrfToken() {
        // Obter CSRF token dos cookies
        const name = 'csrftoken';
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
};

// Inicializar quando o DOM estiver pronto (scripts podem estar em extra_js após o body)
function initAgenda() {
    calendario.init();
}
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAgenda);
} else {
    initAgenda();
}
