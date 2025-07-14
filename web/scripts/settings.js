let bridge = null;
let temp_text = '';
let temp_photo = '';
let selected_sessions = null;

new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.settingsBridge;

    bridge.renderSettingsSessions.connect(renderSettingsSessions);
    bridge.renderSMMMessages.connect(renderSMMMessages);
    bridge.renderChooseSessions.connect(renderChooseSessions);
    bridge.renderParsingProgressData.connect(renderParsingProgressData);
    bridge.renderMailingProgressData.connect(renderMailingProgressData);
    bridge.finishParsing.connect(finishParsing);
    bridge.finishMailing.connect(finishMailing);
    bridge.sessionChangedState.connect(sessionChangedState);
    bridge.renderSettings.connect(renderSettings);
});


async function openSettingsTab(tab_name) {
    document.querySelectorAll('.tab').forEach(
        elem => elem.classList.remove('active-tab')
    );
    document.querySelectorAll('.tab-block').forEach(
        elem => elem.classList.remove('active-tab-block')
    );
    if (tab_name === 'chatting') {
        document.getElementById('chatting-tab').classList.add('active-tab');
        document.getElementById('chatting-tab-block').classList.add('active-tab-block');
    } else if (tab_name === 'mailing') {
        document.getElementById('mailing-tab').classList.add('active-tab');
        document.getElementById('mailing-tab-block').classList.add('active-tab-block');
        if (!document.getElementById('start-mailing-button').disabled) {
            selected_sessions = null;
            document.getElementById('mailing-account-count').innerText = 0;
        }
    } else if (tab_name === 'parsing') {
        document.getElementById('parsing-tab').classList.add('active-tab');
        document.getElementById('parsing-tab-block').classList.add('active-tab-block');
        if (!document.getElementById('start-parsing-button').disabled) {
            selected_sessions = null;
            document.getElementById('parse-account-count').innerText = 0;
        }
    } else if (tab_name === 'smm') {
        document.getElementById('smm-tab').classList.add('active-tab');
        document.getElementById('smm-tab-block').classList.add('active-tab-block');
        document.getElementById('smm-message-list').innerHTML = '';
        await bridge.loadSMM();
    } else if (tab_name === 'sessions') {
        document.getElementById('sessions-tab').classList.add('active-tab');
        document.getElementById('sessions-tab-block').classList.add('active-tab-block');
        document.getElementById('sessions-list').innerHTML = '';
        await bridge.loadSettingsSessions();
    } else if (tab_name === 'common') {
        document.getElementById('common-tab').classList.add('active-tab');
        document.getElementById('common-tab-block').classList.add('active-tab-block');
        bridge.loadSettings();
    }
}

function renderSettingsSessions(sessions_json) {
    const sessions_list = document.getElementById('sessions-list');
    if (!sessions_list) return;

    const sessions = JSON.parse(sessions_json);
    sessions.forEach(session => {
        const row = document.createElement('div');
        row.className = 'row';
        row.dataset.id = session.session_id;
        // <input type="checkbox" ${session.is_active ? 'checked' : ''}>
        row.innerHTML = `
            <div class="session-info">
                Сессия: <span class="session-name">${session.session_file}</span> Номер телефона: <span class="session-phone">${session.phone_number}</span>
            </div>
            <div class="buttons">
                ${session.status === 0
                    ? '<div class="btn start-session-btn"><img src="assets/icons/start.png" alt="start session" class="icons" onclick="startSession(this)"></div>'
                    : session.status === 1
                    ? '<div class="btn stop-session-btn"><img src="assets/icons/stop.png" alt="stop session" class="icons" onclick="stopSession(this)"></div>'
                    : '<div class="btn" style="background-color: blue;"><div class="loader"></div></div>'
                }
                <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
            </div>
        `;
        sessions_list.appendChild(row);
    });
}

async function authorizeToSession() {
    const phone_number_input = document.getElementById('auth-phone-input').value.trim();
    await bridge.saveSession('', '', phone_number_input);
}

async function addSessions(elem) {
    const sessions_list = document.getElementById('sessions-list');
    if (!sessions_list) return;

    const file = elem.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = async function(e) {
            const base64data = e.target.result.split(',')[1];
            await bridge.saveSession(file.name, base64data, '');
            elem.value = '';
        }
        reader.readAsDataURL(file);
    }
}


async function deleteSession(elem) {
    const row = elem.closest('.row');
    const session_id = String(row.dataset.id);
    const session_name = row.querySelector('.session-name').innerText;

    await bridge.deleteSession(session_id, session_name);
    row.remove();
}


async function startSession(elem) {
    const session = elem.closest('.row');
    const session_id = session.dataset.id;
    const session_name = session.querySelector('.session-name').innerText;
    await bridge.startSession(JSON.stringify({"session_id": session_id, "session_name": session_name}));

    elem.closest('.buttons').innerHTML = `
        <div class="btn" style="background-color: blue;"><div class="loader"></div></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
    `;
}

function sessionChangedState(session_id, state) {
    const session_divs = document.querySelectorAll('.sessions .sessions-list .row');
    session_divs.forEach(session_row => {
        if (session_row.dataset.id === session_id) {
            const buttons = session_row.querySelector('.buttons');
            if (state === "started")
                buttons.innerHTML = `
                    <div class="btn stop-session-btn"><img src="assets/icons/stop.png" alt="stop session" class="icons" onclick="stopSession(this)"></div>
                    <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
                `;
            else if (state === "stopped")
                buttons.innerHTML = `
                    <div class="btn start-session-btn"><img src="assets/icons/start.png" alt="start session" class="icons" onclick="startSession(this)"></div>
                    <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
                `;
            return;
        }
    });
}


async function stopSession(elem) {
    const session = elem.closest('.row');
    const session_name = session.querySelector('.session-name').innerText;
    await bridge.stopSession(session_name);

    elem.closest('.buttons').innerHTML = `
        <div class="btn" style="background-color: blue;"><div class="loader"></div></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
    `;
}

async function renderSMMMessages(smm_messages_str) {
    const smm_list = document.getElementById('smm-message-list');
    if (!smm_list) return;
    
    let last_index = -1;
    if (smm_list.innerHTML !== '')
        last_index = Number(smm_list.lastChild.querySelector('.index').innerText.slice(0, -1));      

    const smm_messages = JSON.parse(smm_messages_str);
    smm_messages.forEach((smm_message, index) => {
        const row = document.createElement('div');
        row.classList = 'row';
        row.dataset.id = smm_message.id;
        row.innerHTML = `
            <div class="left-smm-side">
                <div class="index">${last_index === -1 ? index + 1 : last_index + 1}.</div>
                <textarea class="smm-text" disabled>${smm_message.text || ''}</textarea>
                <label>
                    <img class="image-preview" src="${smm_message.photo ? '../assets/smm_images/' + smm_message.photo : 'assets/images/add_image.png'}" alt="add image" onclick="openImage(this)">
                    <input type="file" accept=".jpg,.jpeg,.png" onchange="uploadImage(this)" disabled>
                </label>
            </div>
            <div class="buttons">
                <div class="btn edit-btn"><img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editMessage(this)"></div>
                <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteMessage(this)"></div>
            </div>
        `;
        smm_list.appendChild(row);
    });
}


async function uploadImage(elem) {
    const img = elem.parentElement.querySelector('img');
    const file = elem.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64data = e.target.result.split(',')[1];
            img.src = e.target.result;
            img.dataset.base64 = base64data;
            img.dataset.filename = file.name;
            elem.value = '';
        }
        reader.readAsDataURL(file);
    }
}


async function addSMMMessage() {
    const textarea = document.getElementById('newMessage');
    const img = document.getElementById('newPhoto');

    if (textarea.value === '' && !img.dataset.base64)
        return;

    const newSMMMessage = {
        "text": textarea.value || null,
        "photo": img.dataset.base64 || null,
        "filename": img.dataset.filename || null
    };

    await bridge.addNewSMMMessage(JSON.stringify(newSMMMessage));

    textarea.value = '';
    img.src = 'assets/images/add_image.png';
    delete img.dataset.base64;
    delete img.dataset.filename;
}


async function deleteMessage(elem) {
    const row = elem.closest('.row');
    const smm_message_id = row.dataset.id;
    await bridge.deleteSMMMessage(String(smm_message_id));

    row.remove();
}


function openImage(elem) {
    if (elem.src.includes("add_image.png") || temp_text !== '' || temp_photo !== '') 
        return;
    
    const overlay = document.getElementById('image-preview-overlay');
    const fullimg = document.getElementById('image-preview-fullscreen');
    fullimg.src = elem.src;
    overlay.style.display = 'flex';
}


function editMessage(elem) {
    const row = elem.closest('.row');
    const textarea = row.querySelector('textarea');
    const img_preview = row.querySelector('.image-preview');
    const input_elem = row.querySelector('input');
    const buttons = row.querySelector('.buttons');

    temp_text = textarea.value;
    textarea.disabled = false;
    temp_photo = img_preview.src;
    input_elem.disabled = false;
    buttons.innerHTML = `
        <div class="btn accept-btn"><img class="icons" src="assets/icons/mark.png" alt="accept" onclick="saveChanges(this)"></div>
        <div class="btn cancel-btn"><img class="icons" src="assets/icons/cancel.png" alt="cancel" onclick="discardChanges(this)"></div>
    `;
}


function discardChanges(elem) {
    const row = elem.closest('.row');
    const textarea = row.querySelector('textarea');
    const img_preview = row.querySelector('.image-preview');
    const input_elem = row.querySelector('input');
    const buttons = row.querySelector('.buttons');

    textarea.value = temp_text;
    textarea.disabled = true;
    img_preview.src = temp_photo;
    input_elem.disabled = true;
    buttons.innerHTML = `
        <div class="btn edit-btn"><img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editMessage(this)"></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteMessage(this)"></div>
    `;

    temp_photo = '';
    temp_text = '';
    delete img_preview.dataset.base64;
    delete img_preview.dataset.filename;
}


async function saveChanges(elem) {
    const row = elem.closest('.row');
    const textarea = row.querySelector('textarea');
    const img_preview = row.querySelector('.image-preview');
    
    if (textarea.value === temp_text && !img_preview.dataset.base64) {
        discardChanges(elem);
        return;
    }
    
    const editedSMM = {
        "id": String(row.dataset.id),
        "text": textarea.value || null,
        "photo": img_preview.dataset.base64 || null,
        "filename": img_preview.dataset.filename || null
    };
    
    await bridge.saveChanges(JSON.stringify(editedSMM));
    
    const input_elem = row.querySelector('input');
    const buttons = row.querySelector('.buttons');
    textarea.disabled = true;
    input_elem.disabled = true;
    buttons.innerHTML = `
        <div class="btn edit-btn"><img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editMessage(this)"></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteMessage(this)"></div>
    `;
    
    temp_photo = '';
    temp_text = '';
    delete img_preview.dataset.base64;
    delete img_preview.dataset.filename;
}

function changeMailingType(type) {
    const select_block = document.querySelector('.select-mailing-type');
    if (type === 'usernames') {
        select_block.querySelector('#mailing-database').classList.remove('active-type');
        select_block.querySelector('#mailing-usernames').classList.add('active-type');
    } else if (type === 'db') {
        select_block.querySelector('#mailing-usernames').classList.remove('active-type');
        select_block.querySelector('#mailing-database').classList.add('active-type');
    }
}

function changeParsingType(type) {
    const select_block = document.querySelector('.select-parse-type');
    if (type === 'channel') {
        select_block.querySelector('#parse-group').classList.remove('active-type');
        select_block.querySelector('#parse-channel').classList.add('active-type');
        document.getElementById('parse-group-settings').style.display = 'none';
        document.getElementById('parse-channel-settings').style.display = 'flex';
    } else if (type === 'group') {
        select_block.querySelector('#parse-channel').classList.remove('active-type');
        select_block.querySelector('#parse-group').classList.add('active-type');
        document.getElementById('parse-channel-settings').style.display = 'none';
        document.getElementById('parse-group-settings').style.display = 'flex';
    }
}

function changeGroupParseSettings(type) {
    const select_block = document.querySelector('.parse-group-settings');
    if (type === 'messages') {
        select_block.querySelector('#parse-group-participants').classList.remove('active-type');
        select_block.querySelector('#parse-group-messages').classList.add('active-type');
        document.getElementById('messages-parse-settings').style.display = 'flex';
    } else if (type === 'participants') {
        select_block.querySelector('#parse-group-messages').classList.remove('active-type');
        select_block.querySelector('#parse-group-participants').classList.add('active-type');
        document.getElementById('messages-parse-settings').style.display = 'none';
    }
}

async function loadChooseSessions() {
    await bridge.loadChooseSessions();
}

function renderChooseSessions(sessions_str) {
    const sessions = JSON.parse(sessions_str);
    const modal = document.getElementById('session-modal');
    const sessionList = document.getElementById('session-list');
    sessionList.innerHTML = '';

    sessions.forEach(session => {
        const div = document.createElement('div');
        div.innerHTML = `
        <label>
            <input type="checkbox"
                value="${session.session_id}"
                class="session-checkbox"
                data-file="${session.session_file}">
            ${session.session_file}
        </label>
        `;
        sessionList.appendChild(div);
    });

    modal.classList.remove('hidden');
}

function closeSessionModal() {
    document.getElementById('session-modal').classList.add('hidden');
}

function confirmSelectedSessions() {
    selected_sessions = {};
    document.querySelectorAll('.session-checkbox:checked').forEach(cb => {
        const session_id = parseInt(cb.value, 10);
        const session_file = cb.dataset.file;
        selected_sessions[session_id] = session_file;
    });
    
    const radio_tab_id = document.querySelector('input[name="settings-tabs"][type="radio"]:checked')?.id;
    const count = Object.keys(selected_sessions).length;
    
    if (radio_tab_id === 'tabparsing')
        document.getElementById('parse-account-count').innerText = count;
    else if (radio_tab_id === 'tabmailing')
        document.getElementById('mailing-account-count').innerText = count;

    closeSessionModal();
}

async function startParsing() {
    const parse_links = document.getElementById('parse-links').value.trim();
    const is_parse_channel = document.getElementById('parse-channel').classList.contains('active-type');
    const count_of_posts = document.getElementById('posts-parse-count').value;
    const is_parse_messages = document.getElementById('parse-group-messages').classList.contains('active-type');
    const count_of_messages = document.getElementById('messages-parse-count').value;

    if (!selected_sessions || selected_sessions.length === 0 || !parse_links
        || is_parse_channel && !count_of_posts
        || !is_parse_channel && is_parse_messages && !count_of_messages) {
            bridge.show_notification("Введите корректные данные");
            return;
        }

    const parse_data = {
        parse_links,
        is_parse_channel,
        count_of_posts,
        is_parse_messages,
        count_of_messages,
        selected_sessions
    }
    await bridge.startParsing(JSON.stringify(parse_data));
}

async function stopParsing() {
    await bridge.stopParsing();
}


function renderParsingProgressData(render_data_str) {
    const render_data = JSON.parse(render_data_str);
    const stop_button = document.getElementById('stop-parsing-button');
    const start_button = document.getElementById('start-parsing-button');
    const save_db_button = document.getElementById('save-results-to-computer');
    const export_csv_button = document.getElementById('add-results-to-database');
    if (stop_button.disabled) stop_button.disabled = false;
    if (!start_button.disabled) start_button.disabled = true;
    if (!save_db_button.disabled) save_db_button.disabled = true;
    if (!export_csv_button.disabled) export_csv_button.disabled = true;
    document.getElementById('parsing-status').innerText = render_data.status;
    document.getElementById('total-parsed-count').innerText = render_data.total_count;
    document.getElementById('current-chat').innerText = render_data.chat;
    document.getElementById('parsing-elapsed-time').innerText = render_data.elapsed_time;
}

function finishParsing() {
    document.getElementById('parsing-status').innerText = "завершено";
    document.getElementById('start-parsing-button').disabled = false;
    document.getElementById('stop-parsing-button').disabled = true;
    document.getElementById('save-results-to-computer').disabled = false;
    document.getElementById('add-results-to-database').disabled = false;
}


async function saveToDB() {
    await bridge.saveParsedData('db')
}

async function exportCSV() {
    await bridge.saveParsedData('csv');
}

async function startMailing() {
    const is_parse_usernames = document.getElementById('mailing-usernames').classList.contains('active-type');
    const mailing_data = document.getElementById('mailing-data-field').value.trim();
    const delay = document.getElementById('delay-between-mailing-messages').value;

    if (is_parse_usernames && !mailing_data) {
        bridge.show_notification("Введите корректные данные");
        return;
    }

    const mail_data = {
        is_parse_usernames,
        mailing_data,
        delay,
        selected_sessions
    };

    await bridge.startMailing(JSON.stringify(mail_data));
}

async function stopMailing() {
    await bridge.stopMailing();
}


function renderMailingProgressData(render_data_str) {
    const render_data = JSON.parse(render_data_str);
    const start_button = document.getElementById('start-mailing-button');
    const stop_button = document.getElementById('stop-mailing-button');
    if (!start_button.disabled) start_button.disabled = true;
    if (stop_button.disabled) stop_button.disabled = false;
    document.getElementById('mailing-status').innerText = render_data.status;
    document.getElementById('total-mailed-count').innerText = render_data.total_count;
    document.getElementById('mailing-time').innerText = render_data.time;
}

function finishMailing() {
    document.getElementById('mailing-status').innerText = "завершено";
    document.getElementById('start-mailing-button').disabled = false;
    document.getElementById('stop-mailing-button').disabled = true;
}


function renderSettings(settings_str) {
    const settings = JSON.parse(settings_str);
    let setting_elem = document.getElementById('force-parse-to-db');
    setting_elem.checked = settings.force_parse_to_db;
    setting_elem = document.getElementById('fetch-sessions-old-dialogs');
    setting_elem.checked = settings.fetch_sessions_old_dialogs;
    
}


function changeSettings(elem) {
    const elem_type = elem.type;
    const key = elem.name;
    let value = null;
    if (elem_type === 'checkbox') {
        value = elem.checked;
    }

    bridge.changeSettings(JSON.stringify({key, value}));
}


function resetSettings() {
    bridge.resetSettings();
}