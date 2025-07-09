let bridge = null;
let currentDialogId = null;
let currentDialogDiv = null;

new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.sidebarBridge;

    bridge.renderSelectSessions.connect(renderSelectSessions);
    bridge.renderDialogs.connect(renderDialogs);
    bridge.deleteSessionFromSelect.connect(deleteSessionFromSelect);
});


document.addEventListener('click', e => {
    const context_menu = document.getElementById('context-menu');
    if (!context_menu.contains(e.target)) {
        context_menu.style.display = 'none';
        currentDialogDiv = null;
        currentDialogId = null;
    }
})


function renderSelectSessions(sessions_str) {
    const select = document.getElementById('choose-session');
    const sessions = JSON.parse(sessions_str);

    sessions.forEach(session => {
        const option = document.createElement('option');
        option.value = session.session_id;
        option.textContent = session.session_file;
        select.appendChild(option);
    });

    select.value = sessions[0].session_id;
}


function deleteSessionFromSelect(session_id) {
    const select = document.getElementById('choose-session');
    
    for (let i = 0; i < select.options.length; i++)
        if (select.options[i].value === session_id) {
            select.remove(i);
            break;
        }
    
    if (select.options.length === 0)
        document.getElementById('dialogs').innerHTML = '';
    else {
        select.value = select.options[0].value;
        changeSession();
    }
}
    

function renderDialogs(dialogs_raw) {
    const sidebar = document.getElementById('dialogs');
    if (!sidebar) return;
    
    const dialogs = JSON.parse(dialogs_raw);
    const select_elem = document.getElementById('choose-session')
    const session_filename = select_elem.options[select_elem.selectedIndex].textContent;
    dialogs.forEach(dialog => {
        const dialog_div = document.createElement('div');
        dialog_div.className = "dialog";
        // dialog_div.dataset.id = dialog.user_id;

        dialog_div.innerHTML = `
            <div class="lef-side">
                <img src="${dialog.profile_photo ? '../assets/profile_photos/' + session_filename + '/' + dialog.profile_photo : 'assets/images/profile.png'}" alt="${dialog.profile_photo}" class="profile-photo">
            </div>
            <div class="right-side">
                <div class="name">${dialog.first_name} ${dialog.last_name}</div>
                <div class="last-message">${dialog.last_message ? dialog.last_message : '[Attachment]'}</div>
                <div class="last-message-time">${dialog.created_at}</div>
            </div>
        `;

        dialog_div.onclick = () => {
            document.querySelectorAll('.dialog.active').forEach(
                elem => elem.classList.remove('active')
            );
            dialog_div.classList.add('active');
            bridge.selectDialog(String(dialog.user_id));
        };
        dialog_div.oncontextmenu = (event) => {
            event.preventDefault();
            currentDialogId = dialog.user_id;
            currentDialogDiv = dialog_div;

            const menu = document.getElementById('context-menu');
            menu.style.top = `${event.pageY}px`;
            menu.style.left = `${event.pageX}px`;
            menu.style.display = 'block';
        }
        sidebar.appendChild(dialog_div);
    });
}


async function deleteDialog() {
    if (!currentDialogId) return;

    await bridge.deleteDialog(String(currentDialogId));
    document.getElementById('context-menu').style.display = 'none';
    currentDialogDiv.remove();
    currentDialogDiv = null;
    currentDialogId = null;
}


function changeSession() {
    document.getElementById('dialogs').innerHTML = '';
    const select_session = document.getElementById('choose-session');
    const session_id = select_session.options[select_session.selectedIndex].value;
    const session_file = select_session.options[select_session.selectedIndex].textContent;
    bridge.changeSession(JSON.stringify({"session_id": session_id, "session_file": session_file}));
}


function openSettings() {
    bridge.openSettings();
}