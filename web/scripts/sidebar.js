let bridge = null;
let currentDialogId = null;
let currentDialogDiv = null;
const FILTER_MASKS = {
    'new_dialog': s => !(s & 0b100) && !(s & 0b010),
    'old_dialog': s => !(s & 0b100) && (s & 0b010),
    'parser_dialog': s => (s & 0b100) && !(s & 0b010) && !(s & 0b001),
    'mailer_dialog': s => (s & 0b100) && !(s & 0b010) && (s & 0b001),
    'searched_dialog': s => (s & 0b100) && (s & 0b010)
};

new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.sidebarBridge;

    bridge.renderSelectSessions.connect(renderSelectSessions);
    bridge.renderDialogs.connect(renderDialogs);
    bridge.removeDialog.connect(removeDialog);
    bridge.deleteSessionFromSelect.connect(deleteSessionFromSelect);
    bridge.renderMessageNotifications.connect(renderMessageNotifications);
    bridge.setUnreadDialog.connect(setUnreadDialog);
    bridge.renderFilters.connect(renderFilters);
});


async function searchUsername() {
    const search_input = document.getElementById('search-user');
    const search_value = search_input.value?.replace(/[^0-9A-Za-z_]/g, '').slice(0, 32);
    if (search_value.length < 5) {
        bridge.show_notification("Неверный username");
        return;
    }

    await bridge.searchUsername(search_value);
    search_input.value = '';
    filterData(search_input);
}


function filterEntities() {
    const values = [];
    document.querySelectorAll('.filter-menu input[type="checkbox"]').forEach(checkbox => {
        const is_enable = checkbox.checked;
        values.push(is_enable);
        const lambda = FILTER_MASKS[checkbox.value];
        document.querySelectorAll('.dialog').forEach(dialog => {
            if (lambda(parseInt(dialog.dataset.status)))
                dialog.classList.toggle('filtered-out', !is_enable);
        });
    });
    bridge.changeSettings(JSON.stringify({'key': 'dialog_filters', 'value': values}));
}


function filterData(elem) {
    const search = elem.value.toLowerCase();
    document.querySelectorAll('.dialog').forEach(dialog => {
        if (dialog.style.display === 'none') return;
        const name = dialog.querySelector('.name')?.textContent?.toLowerCase() || '';
        const username = dialog.dataset.username?.toLowerCase() || '';
        const match = [name, username].some(text => text.includes(search));

        dialog.classList.toggle('searched-hidden', !match);
    });
}


document.addEventListener('click', e => {
    const context_menu = document.getElementById('context-menu');
    const notification_popup = document.getElementById('notification-popup');
    if (!context_menu.contains(e.target)) {
        context_menu.style.display = 'none';
        currentDialogDiv = null;
        currentDialogId = null;
    }
    if (!notification_popup.contains(e.target)) {
        notification_popup.hidden = true;
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
        dialog_div.dataset.user_id = dialog.user_id;
        dialog_div.dataset.status = dialog.status;
        dialog_div.dataset.username = dialog.username;
        let profile_photo = '';
        if (dialog.profile_photo) {
            if (dialog.profile_photo.endsWith('.mp4'))
                profile_photo = `<div class="profile-photo" style="background-color: blue; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: bold;">Video</div>`;
            else
                profile_photo = `<img src="../assets/profile_photos/${session_filename}/${dialog.profile_photo}" alt="${dialog.profile_photo}" class="profile-photo"></img>`;
        } else
            profile_photo = `<img src="assets/images/profile.png" alt="${dialog.profile_photo}" class="profile-photo"></img>`;

        // ${dialog.profile_photo.endsWith('.mp4')
        //     ? "<video src" + dialog
        //     : "<img src=" + dialog.profile_photo ? '../assets/profile_photos/' + session_filename + '/' + dialog.profile_photo : 'assets/images/profile.png'}" alt="${dialog.profile_photo}" class="profile-photo"></img>
        // }
        const user_full_name = `${dialog.first_name} ${dialog.last_name}`;
        dialog_div.innerHTML = `
            <div class="lef-side">
                ${profile_photo}
            </div>
            <div class="right-side">
                <div class="name">${user_full_name}</div>
                <div class="message-line">
                    <div class="last-message">${dialog.last_message ? dialog.last_message : '[Attachment]'}</div>
                    <img class="unread-dialog" src="assets/icons/message.png" style="display: ${dialog.is_read ? 'none' : 'block'}">
                </div>
                <div class="last-message-time">${dialog.created_at}</div>
            </div>
        `;

        dialog_div.onclick = () => {
            document.querySelectorAll('.dialog.active').forEach(
                elem => elem.classList.remove('active')
            );
            dialog_div.classList.add('active');
            dialog_div.querySelector('.unread-dialog').style.display = 'none';
            const user_data = {
                profile_photo,
                user_full_name,
                "username": dialog.username
            };
            bridge.selectDialog(String(dialog.user_id), JSON.stringify(user_data));
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
    filterEntities();
}


function openFilter() {
    const filter_menu = document.getElementById('filter-menu');
    filter_menu.hidden = !filter_menu.hidden;
}

function renderFilters(settings_str) {
    const settings = JSON.parse(settings_str);
    document.querySelectorAll('.filter-menu input[type="checkbox"]').forEach((checkbox, index) =>
        checkbox.checked = settings[index]
    );
}


function setUnreadDialog(user_id) {
    const sidebar = document.getElementById('dialogs');
    sidebar.childNodes.forEach(dialog => {
        if (dialog.dataset.user_id === user_id) {
            dialog.querySelector('.unread-dialog').style.display = 'block';
            return;
        }
    });
}


async function deleteDialog() {
    if (!currentDialogId) return;

    await bridge.deleteDialog(String(currentDialogId));
    document.getElementById('context-menu').style.display = 'none';
}


function removeDialog() {
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


function openNotifications() {
    bridge.fetchNotifications();
}

function renderMessageNotifications(notifications_str) {
    const notification_popup = document.getElementById('notification-popup');
    const notification_list = document.getElementById('notification-list');
    const notifications = JSON.parse(notifications_str);
    notification_list.innerHTML = '';

    if (!Object.keys(notifications).length) {
        const li = document.createElement('li');
        li.textContent = "Нет уведомлений";
        notification_list.appendChild(li);
    } else {
        for (const [session_id, messages] of Object.entries(notifications)) {
            const header = document.createElement('li');
            header.textContent = `Сессия ${session_id}`;
            header.style.fontWeight = 'bold';
            header.style.borderBottom = '1px solid #0562dd';
            header.style.marginTop = '10px';
            notification_list.appendChild(header);

            messages.forEach(({user_id, message_text}) => {
                const li = document.createElement('li');
                li.textContent = `Пользователь ${user_id}. Сообщение: ${message_text}`;
                notification_list.appendChild(li);
            })
        }
    }
    notification_popup.hidden = false;
}


function openSettings() {
    bridge.openSettings();
}