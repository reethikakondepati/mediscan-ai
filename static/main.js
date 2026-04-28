// ============================================
//  MEDISCAN AI — main.js
// ============================================

document.addEventListener('DOMContentLoaded', () => {

    // ---- Scroll Animation Observer ----
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('in-view');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.step-card, .feature-card, .report-type-card, .result-section-card').forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(30px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });

    const style = document.createElement('style');
    style.textContent = '.in-view { opacity: 1 !important; transform: translateY(0) !important; }';
    document.head.appendChild(style);

    // ---- Drag and Drop ----
    const dropZone = document.getElementById('dropZone');
    if (dropZone) {
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('drag-over');
        });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file) {
                const input = document.getElementById('fileInput');
                const dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                handleFileSelect(input);
            }
        });
    }

    // ---- Navbar scroll effect ----
    const navbar = document.querySelector('.navbar');
    if (navbar) {
        window.addEventListener('scroll', () => {
            navbar.style.boxShadow = window.scrollY > 50
                ? '0 4px 30px rgba(0,0,0,0.4)' : 'none';
        });
    }

    // ---- Animate result cards ----
    document.querySelectorAll('.animate-card').forEach((card, i) => {
        card.style.animationDelay = `${i * 0.1}s`;
        card.style.animationFillMode = 'both';
    });

    // ---- Smooth anchor scroll ----
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                e.preventDefault();
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

    // ---- Auto-dismiss alerts ----
    document.querySelectorAll('.alert').forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.5s ease';
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 500);
        }, 4000);
    });

    // ---- Boot MediBot widget ----
    initMediBot();
});


// ---- File Select Handler ----
function handleFileSelect(input) {
    const file = input.files[0];
    if (!file) return;

    const preview  = document.getElementById('filePreview');
    const nameEl   = document.getElementById('fileName');
    const sizeEl   = document.getElementById('fileSize');
    const iconEl   = document.getElementById('fileIcon');
    if (!preview) return;

    const ext = file.name.split('.').pop().toLowerCase();
    const icons = { pdf: '📄', jpg: '🖼️', jpeg: '🖼️', png: '🖼️', txt: '📝' };
    iconEl.textContent = icons[ext] || '📁';
    nameEl.textContent = file.name;
    sizeEl.textContent = formatFileSize(file.size);
    preview.style.display = 'block';

    const dropZone = document.getElementById('dropZone');
    if (dropZone) {
        dropZone.style.padding = '24px 40px';
        const content = dropZone.querySelector('.drop-zone-content');
        if (content) content.style.display = 'none';
    }
}


// ---- Remove File ----
function removeFile() {
    const input    = document.getElementById('fileInput');
    const preview  = document.getElementById('filePreview');
    const dropZone = document.getElementById('dropZone');
    if (input)   input.value = '';
    if (preview) preview.style.display = 'none';
    if (dropZone) {
        dropZone.style.padding = '60px 40px';
        const content = dropZone.querySelector('.drop-zone-content');
        if (content) content.style.display = 'block';
    }
}


// ---- Handle Form Submit ----
function handleSubmit(e) {
    const input = document.getElementById('fileInput');
    if (!input || !input.files.length) return;

    const overlay   = document.getElementById('loadingOverlay');
    const btnText   = document.getElementById('btnText');
    const btnLoader = document.getElementById('btnLoader');

    if (overlay)   overlay.style.display = 'flex';
    if (btnText)   btnText.style.display = 'none';
    if (btnLoader) btnLoader.style.display = 'flex';

    const steps    = ['step1','step2','step3','step4'];
    const messages = [
        'Uploading your file...',
        'Reading and extracting text...',
        'AI is analyzing your report...',
        'Generating simplified results...'
    ];

    let current = 0;
    const msgEl = document.getElementById('loadingMsg');

    const interval = setInterval(() => {
        current++;
        if (current < steps.length) {
            const stepEl = document.getElementById(steps[current]);
            if (stepEl) stepEl.classList.add('active');
            if (msgEl)  msgEl.textContent = messages[current];
        } else {
            clearInterval(interval);
        }
    }, 1800);
}


// ---- Format File Size ----
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B','KB','MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}


// ============================================================
//  MEDIBOT — Floating Medical Chatbot Widget
// ============================================================

function initMediBot() {
    // ── 1. Inject HTML into body ──────────────────────────
    const html = `
    <!-- MediBot Toggle Button -->
    <button id="medibot-toggle" title="Ask MediBot — Medical Q&A">
        🩺
        <div id="medibot-badge"></div>
    </button>

    <!-- MediBot Chat Panel -->
    <div id="medibot-panel" role="dialog" aria-label="MediBot Medical Assistant">

        <!-- Header -->
        <div class="medibot-header">
            <div class="medibot-avatar">🤖</div>
            <div class="medibot-header-info">
                <strong>MediBot</strong>
                <span>● Online — Medical AI Assistant</span>
            </div>
            <div class="medibot-header-btns">
                <button class="medibot-clear-btn" id="medibot-clear" title="Clear chat">🗑</button>
                <button class="medibot-close-btn" id="medibot-close" title="Close">✕</button>
            </div>
        </div>

        <!-- Messages -->
        <div class="medibot-messages" id="medibot-messages"></div>

        <!-- Quick suggestion chips -->
        <div class="medibot-suggestions" id="medibot-suggestions">
            <button class="medibot-chip">What is diabetes?</button>
            <button class="medibot-chip">What does high HbA1c mean?</button>
            <button class="medibot-chip">Normal blood pressure range?</button>
            <button class="medibot-chip">What is cholesterol?</button>
            <button class="medibot-chip">Symptoms of anemia?</button>
        </div>

        <!-- Input area -->
        <div class="medibot-input-area">
            <input
                type="text"
                id="medibot-input"
                placeholder="Ask a medical question…"
                autocomplete="off"
                maxlength="500"
            />
            <button id="medibot-send" title="Send">➤</button>
        </div>
    </div>`;

    document.body.insertAdjacentHTML('beforeend', html);

    // ── 2. Wire up elements ───────────────────────────────
    const toggle   = document.getElementById('medibot-toggle');
    const panel    = document.getElementById('medibot-panel');
    const closeBtn = document.getElementById('medibot-close');
    const clearBtn = document.getElementById('medibot-clear');
    const input    = document.getElementById('medibot-input');
    const sendBtn  = document.getElementById('medibot-send');
    const msgArea  = document.getElementById('medibot-messages');
    const badge    = document.getElementById('medibot-badge');
    const chips    = document.querySelectorAll('.medibot-chip');

    let history    = [];  // conversation history for context
    let isOpen     = false;
    let isTyping   = false;

    // ── 3. Show welcome message on first open ─────────────
    let welcomed = false;

    function openPanel() {
        isOpen = true;
        panel.classList.add('medibot-open');
        toggle.style.animation = 'none';
        hideBadge();
        input.focus();

        if (!welcomed) {
            welcomed = true;
            appendBotMsg(
                "👋 Hi! I'm <strong>MediBot</strong>, your medical AI assistant.<br><br>" +
                "I can help you understand medical conditions, symptoms, lab values, " +
                "medications, and general health questions.<br><br>" +
                "What would you like to know? 🏥"
            );
        }
    }

    function closePanel() {
        isOpen = false;
        panel.classList.remove('medibot-open');
        toggle.style.animation = 'medibot-pulse 3s ease-in-out infinite';
    }

    function showBadge() {
        if (!isOpen) {
            badge.style.display = 'flex';
        }
    }

    function hideBadge() {
        badge.style.display = 'none';
    }

    // ── 4. Toggle open/close ──────────────────────────────
    toggle.addEventListener('click', () => {
        isOpen ? closePanel() : openPanel();
    });
    closeBtn.addEventListener('click', closePanel);

    // Close when clicking outside panel (but not toggle)
    document.addEventListener('click', (e) => {
        if (isOpen && !panel.contains(e.target) && e.target !== toggle && !toggle.contains(e.target)) {
            closePanel();
        }
    });

    // ── 5. Clear chat ─────────────────────────────────────
    clearBtn.addEventListener('click', () => {
        msgArea.innerHTML = '';
        history = [];
        welcomed = false;
        // Re-show welcome after clear
        appendBotMsg(
            "Chat cleared! 🧹 Ask me any medical question and I'll do my best to help."
        );
    });

    // ── 6. Send message ───────────────────────────────────
    function sendMessage() {
        const text = input.value.trim();
        if (!text || isTyping) return;

        appendUserMsg(text);
        history.push({ role: 'user', content: text });
        input.value = '';
        sendBtn.disabled = true;

        showTyping();
        isTyping = true;

        // Hide suggestion chips after first message
        const suggestionsEl = document.getElementById('medibot-suggestions');
        if (suggestionsEl) suggestionsEl.style.display = 'none';

        const chatUrl = window.MEDIBOT_CHAT_URL || '/chat';
        fetch(chatUrl, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ message: text, history: history })
        })
        .then(r => r.json())
        .then(data => {
            removeTyping();
            isTyping = false;
            sendBtn.disabled = false;

            if (data.error) {
                appendBotMsg('⚠️ Sorry, I ran into an error: ' + data.error);
            } else {
                const reply = data.reply || 'Sorry, I could not generate a response.';
                appendBotMsg(reply.replace(/\n/g, '<br>'));
                history.push({ role: 'assistant', content: reply });

                // Show badge if panel is closed
                if (!isOpen) showBadge();
            }
        })
        .catch(() => {
            removeTyping();
            isTyping = false;
            sendBtn.disabled = false;
            appendBotMsg('⚠️ Connection error. Please check you are logged in and try again.');
        });
    }

    sendBtn.addEventListener('click', sendMessage);

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // ── 7. Suggestion chips ───────────────────────────────
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            input.value = chip.textContent;
            sendMessage();
        });
    });

    // ── 8. DOM helpers ────────────────────────────────────
    function appendUserMsg(text) {
        const div = document.createElement('div');
        div.className = 'medibot-msg user-msg';
        div.innerHTML = `<div class="medibot-bubble">${escapeHtml(text)}</div>`;
        msgArea.appendChild(div);
        scrollToBottom();
    }

    function appendBotMsg(html) {
        const div = document.createElement('div');
        div.className = 'medibot-msg bot-msg';
        div.innerHTML = `
            <div class="medibot-msg-avatar">🤖</div>
            <div class="medibot-bubble">${html}</div>`;
        msgArea.appendChild(div);
        scrollToBottom();
    }

    function showTyping() {
        const div = document.createElement('div');
        div.className = 'medibot-msg bot-msg medibot-typing';
        div.id = 'medibot-typing-indicator';
        div.innerHTML = `
            <div class="medibot-msg-avatar">🤖</div>
            <div class="medibot-bubble">
                <div class="typing-dots">
                    <span></span><span></span><span></span>
                </div>
            </div>`;
        msgArea.appendChild(div);
        scrollToBottom();
    }

    function removeTyping() {
        const el = document.getElementById('medibot-typing-indicator');
        if (el) el.remove();
    }

    function scrollToBottom() {
        msgArea.scrollTop = msgArea.scrollHeight;
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
}