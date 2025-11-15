let bridge = null;
let temp_text = "";
let temp_photo = "";
let selectedParseSessions = {};
let selectedMailSessions = {};
let sessionsList = [];
let openedSettingsTabName = undefined;
let currentVoicePlayer = null;
const stopPlay = () => {
    if (!currentVoicePlayer) {
        return;
    }
    currentVoicePlayer.audio.pause();
    currentVoicePlayer.audio.currentTime = 0;
    currentVoicePlayer.play_btn.textContent = "▶";
    currentVoicePlayer.progress.value = 0;
    currentVoicePlayer.time.textContent = "0:00";
    currentVoicePlayer = null;
};
const observer = new MutationObserver((mutationList) => {
    for (const mutation of mutationList) {
        if (
            mutation.type === "attributes" &&
            mutation.attributeName === "class" &&
            !mutation.target.classList.contains("active-tab-block")
        ) {
            toggleSessionContainerView(true);
            stopPlay();
            return;
        }
    }
});

new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.settingsBridge;

    bridge.renderSessions.connect(renderSessions);
    bridge.renderSMMMessages.connect(renderSMMMessages);
    bridge.renderChooseSessions.connect(renderChooseSessions);
    bridge.renderParsingProgressData.connect(renderParsingProgressData);
    bridge.renderMailingProgressData.connect(renderMailingProgressData);
    bridge.finishParsing.connect(finishParsing);
    bridge.finishMailing.connect(finishMailing);
    bridge.sessionChangedState.connect(sessionChangedState);
    bridge.renderSettings.connect(renderSettings);
    bridge.removeSessionRow.connect(removeSessionRow);
    bridge.renderVoiceMessages.connect(renderVoiceMessages);
    bridge.removeVoiceMessageRow.connect(removeVoiceMessageRow);
    bridge.renderObjects.connect(renderObjects);
});

observer.observe(document.getElementById("voice-smm-block"), {
    attributeFilter: ["class"],
});
observer.observe(document.getElementById("smm-tab-block"), {
    attributeFilter: ["class"],
});

async function openSettingsTab(tab_name) {
    openedSettingsTabName = tab_name;

    document
        .querySelectorAll(".main-tabs .tab")
        .forEach((elem) => elem.classList.remove("active-tab"));

    document
        .querySelectorAll(".tab-block")
        .forEach((elem) => elem.classList.remove("active-tab-block"));

    if (tab_name === "chatting") {
        document.getElementById("chatting-tab").classList.add("active-tab");
        document
            .getElementById("chatting-tab-block")
            .classList.add("active-tab-block");
    } else if (tab_name === "mailing") {
        document.getElementById("mailing-tab").classList.add("active-tab");
        document
            .getElementById("mailing-tab-block")
            .classList.add("active-tab-block");
        const isDisabled = document.getElementById("start-mailing-button").disabled;
        const selectedSessionsCount = Object.keys(selectedMailSessions).length;
        if (!isDisabled) {
            document.getElementById("mailing-account-count").innerText = String(
                selectedSessionsCount,
            );
        }
    } else if (tab_name === "parsing") {
        document.getElementById("parsing-tab").classList.add("active-tab");
        document
            .getElementById("parsing-tab-block")
            .classList.add("active-tab-block");
        const isDisabled = document.getElementById("start-parsing-button").disabled;
        const selectedSessionsCount = Object.keys(selectedParseSessions).length;
        if (!isDisabled) {
            document.getElementById("parse-account-count").innerText = String(
                selectedSessionsCount,
            );
        }
    } else if (tab_name === "smm") {
        document.getElementById("smm-tab").classList.add("active-tab");
        document.getElementById("smm-tab-block").classList.add("active-tab-block");
        document.getElementById("smm-message-list").innerHTML = "";
        await bridge.loadSMM();
    } else if (tab_name === "sessions") {
        document.getElementById("sessions-tab").classList.add("active-tab");
        document
            .getElementById("sessions-tab-block")
            .classList.add("active-tab-block");
        document.getElementById("sessions-list").innerHTML = "";
        await bridge.loadSessions(true);
    } else if (tab_name === "common") {
        document.getElementById("common-tab").classList.add("active-tab");
        document
            .getElementById("common-tab-block")
            .classList.add("active-tab-block");
        bridge.loadSettings();
    }
}

async function openSMMSettingsTab(tab_name) {
    document
        .querySelector(".smm-tabs .tab.active-tab")
        ?.classList.remove("active-tab");

    document
        .querySelector(".tab-block .smm-block.active-tab-block")
        ?.classList.remove("active-tab-block");

    if (tab_name === "text") {
        document.getElementById("text-tab").classList.add("active-tab");
        document.getElementById("text-smm-block").classList.add("active-tab-block");
    } else if (tab_name === "voice") {
        document.getElementById("voice-tab").classList.add("active-tab");
        document
            .getElementById("voice-smm-block")
            .classList.add("active-tab-block");
        document.getElementById("smm-voice-messages-block").innerHTML = "";
        await bridge.loadVoiceMessages();
    }
}

function representTime(time) {
    const m = Math.floor(time / 60);
    const s = Math.floor(time % 60)
        .toString()
        .padStart(2, "0");
    return `${m}:${s}`;
}

function createPlayer(voice_path, voice_id) {
    const player = document.createElement("div");
    player.dataset.id = voice_id;
    player.className = "audio-player";
    player.innerHTML = `
        <div class="play-btn">▶</div>
        <div class="time-progress">0:00</div>
        <input type="range" class="progress" value="0" min="0" max="100">
        <span class="duration">0:00</span>
        <audio src="${voice_path}"></audio>
    `;

    const progress = player.querySelector(".progress");
    const audio = player.querySelector("audio");
    const time = player.querySelector(".time-progress");

    audio.addEventListener("loadedmetadata", () => {
        player.querySelector(".duration").textContent = representTime(
            audio.duration,
        );
    });
    progress.addEventListener("input", () => {
        countVoiceCurrentTime(audio, progress);
    });
    audio.addEventListener("timeupdate", () => {
        handleVoiceTimeUpdate(audio, progress, time);
    });

    return player;
}

function countDuration(player, audio) {
    player.querySelector(".duration").textContent = representTime(audio.duration);
}

function countVoiceCurrentTime(audio, progress) {
    if (!audio || !isFinite(audio.duration) || audio.duration <= 0) return;
    audio.currentTime = (progress.value / 100) * audio.duration;
}

function handleVoiceTimeUpdate(audio, progress, time) {
    if (!isFinite(audio.duration)) return;

    if (audio.ended) {
        stopPlay();
        return;
    }

    progress.value = (audio.currentTime / audio.duration) * 100 || 0;
    time.textContent = representTime(audio.currentTime);
}

document.addEventListener("click", async (e) => {
    const target = e.target;
    if (target.classList.contains("play-btn")) {
        toggleVoicePlay(e.target);
        return;
    }

    if (target.matches("div#cancel-button")) {
        document.querySelector(".overlay .add-voice-window")?.remove("open");
        return;
    }

    if (target.matches("div#add-button")) {
        const add_window = document.querySelector(".overlay .add-voice-window");
        if (add_window) {
            const name_field = add_window.querySelector("#add-voice-name");
            if (!name_field.value) {
                name_field.classList.add("attention");
                setTimeout(() => {
                    name_field.classList.remove("attention");
                }, 3000);
                return;
            }
            const path = add_window.dataset.path;
            const desc = add_window.querySelector("#add-voice-desc").value;
            await bridge.addVoiceMessage(name_field.value, desc, path);
            add_window.classList.remove("open");
            return;
        }
    }

    const row = target.closest(".smm-voice-messages-block .row");
    if (!row) return;

    if (target.closest(".delete-btn")) {
        const id = row.querySelector(".audio-player")?.dataset.id;
        if (id) await bridge.deleteVoiceMessage(String(id));
    } else if (target.closest(".voice-message-desc-btn")) {
        row.querySelector(".voice-desc-slider")?.classList.toggle("slide");
    }
});

document.addEventListener("change", async (e) => {
    if (e.target.matches(".voice-message-row-side input[type=checkbox]")) {
        const id = e.target.closest(".row")?.querySelector(".audio-player")
            ?.dataset.id;
        if (id) await bridge.changeVoiceSelect(String(id), e.target.checked);
    }
});

function toggleVoicePlay(elem) {
    const player = elem.closest(".audio-player");
    const player_id = player?.dataset.id;

    if (currentVoicePlayer) {
        if (currentVoicePlayer?.id === player_id) {
            if (currentVoicePlayer.audio.paused) {
                currentVoicePlayer.audio.play();
                elem.textContent = "⏸";
            } else {
                currentVoicePlayer.audio.pause();
                elem.textContent = "▶";
            }
            return;
        } else {
            stopPlay();
        }
    }

    currentVoicePlayer = {
        id: player_id,
        player: player,
        play_btn: player.querySelector(".play-btn"),
        progress: player.querySelector(".progress"),
        audio: player.querySelector("audio"),
        time: player.querySelector(".time-progress"),
    };
    currentVoicePlayer.audio.play();
    currentVoicePlayer.play_btn.textContent = "⏸";
}

async function renderVoiceMessages(voice_msgs_str) {
    const voice_msgs = JSON.parse(voice_msgs_str);
    const voice_messages_block = document.getElementById(
        "smm-voice-messages-block",
    );
    const voices_fragment = document.createDocumentFragment();

    voice_msgs.forEach((voice_msg) => {
        const voice_row = document.createElement("div");
        voice_row.className = "row";
        voice_row.innerHTML = `
            <div class="row-content">
                <div class="voice-message-row-side">
                    <input type="checkbox" ${voice_msg.selected ? "checked" : ""}>
                    <div class="voice-desc-viewport">
                        <div class="voice-desc-slider">
                            <div class="voice-desc audio-name">${voice_msg.name}</div>
                            <div class="voice-desc voice-message-desc">${voice_msg.desc}</div>
                        </div>
                    </div>
                </div>
                <div class="voice-message-row-side right-side">
                    <div class="voice-message-desc-btn">🛈</div>
                    <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete"></div>
                </div>
            </div>
        `;
        voice_row
            .querySelector(".right-side")
            .prepend(createPlayer(voice_msg.path, voice_msg.id));

        voices_fragment.appendChild(voice_row);
    });
    voice_messages_block.appendChild(voices_fragment);
}

async function toggleSessionContainerView(force = null) {
    const icon = document.querySelector(
        ".smm-session-container-title .title-icon",
    );
    const block = document.querySelector("#smm-session-container-block");

    if (force) {
        icon?.classList.remove("open");
        block?.classList.remove("open");
        return;
    }

    const isOpen = block?.classList.toggle("open");
    icon?.classList.toggle("open", isOpen);

    if (isOpen) {
        block.querySelector(".sessions-list").innerHTML = "";
        await bridge.loadSessions(false);
    }
}

function removeVoiceMessageRow(voice_msg_id_str) {
    if (currentVoicePlayer?.id === voice_msg_id_str) {
        stopPlay();
    }

    document
        .querySelector(
            `#smm-voice-messages-block .audio-player[data-id="${voice_msg_id_str}"]`,
        )
        ?.closest(".row")
        ?.remove();
}

async function renderSessions(sessions_json, is_settings) {
    console.log(sessions_json)
    const sessions_list = document.querySelector(
        `${is_settings ? "#sessions-tab-block" : "#smm-session-container-block"} .sessions-list`,
    );
    if (!sessions_list) return;

    const fragment = document.createDocumentFragment();
    const sessions = JSON.parse(sessions_json);
    sessions.forEach((session) => {
        const row = document.createElement("div");
        row.className = "row";
        row.dataset.id = session.session_id;
        row.innerHTML = `
            <div class="row-content">
                <div class="session-info">
                    Сессия: <span class="session-name">${session.session_file}</span> Номер телефона: <span class="session-phone">${session.phone_number}</span>
                </div>
            </div>
        `;

        if (is_settings) {
            let statusButton = "";
            if (session.status === 0) {
                statusButton = `
                    <div class="btn start-session-btn">
                        <img src="assets/icons/start.png" alt="start session" class="icons" onclick="startSession(this)">
                    </div>
                `;
            } else if (session.status === 1) {
                statusButton = `
                    <div class="btn stop-session-btn">
                        <img src="assets/icons/stop.png" alt="stop session" class="icons" onclick="stopSession(this)">
                    </div>
                `;
            } else {
                statusButton = `
                    <div class="btn" style="background-color: blue;">
                        <div class="loader"></div>
                    </div>
                `;
            }
            row.querySelector(".row-content").insertAdjacentHTML(
                "beforeend",
                `
                <div class="buttons">
                    ${statusButton}
                    <div class="btn delete-btn">
                        <img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)">
                    </div>
                </div>
            `,
            );
        } else {
            row.addEventListener("click", async () => {
                pushWindow("dialogs", session.session_id, session.session_file);
                // setTimeout(async () => {
                await bridge.get_session_dialogs(
                    String(session.session_id),
                    session.session_file,
                    true,
                );
                // }, 3000);
            });
        }
        fragment.appendChild(row);
    });
    sessions_list.appendChild(fragment);
}

function makeProgressBar() {
    return '<div class="progress-bar">Загрузка...<div class="progress-bar-container"><div class="progress-bar-track"></div></div></div>';
}

function goBack() {
    document.getElementById("smm-slider")?.classList.toggle("slide", false);
    document.getElementById("smm-voices").innerHTML = "";
    stopPlay();
}

function pushWindow(type, target_id_str, target_name) {
    document.getElementById("overlay")?.classList.toggle("open", true);
    const push_window = document.getElementById(`smm-${type}-window`);
    push_window.querySelector(`.smm-${type}`).innerHTML = "";
    push_window.dataset.id = target_id_str;
    push_window.querySelector(`.${type}-target-name`).textContent = target_name;
    push_window.insertAdjacentHTML("beforeend", makeProgressBar());
    document
        .getElementById("smm-slider")
        ?.classList.toggle("slide", type === "voices");
}

async function renderObjects(
    type,
    target_id_str,
    session_file,
    targets_str,
    isFavorite,
) {
    const target_window = document.getElementById(`smm-${type}-window`);
    if (target_window.dataset.id !== target_id_str) {
        return;
    }
    target_window.querySelector(".progress-bar").remove();

    const targets_list = target_window.querySelector(`.smm-${type}`);
    const fragment = document.createDocumentFragment();
    const targets = JSON.parse(targets_str);

    targets.forEach((target) => {
        const target_row = document.createElement("div");
        if (type === "dialogs") {
            target_row.className = "modal-window-row modal-window-dialog-row";
            target_row.dataset.id = target.id;
            target_row.innerHTML = `<div class="dialog-title">${target.title}</div>`;
            target_row.addEventListener("click", async () => {
                pushWindow("voices", target.id, target.title);
                // setTimeout(async () => {
                await bridge.get_dialog_voices(
                    String(target.id),
                    target_id_str,
                    session_file,
                );
                // }, 3000);
            });
        } else if (type === "voices") {
            target_row.className = "modal-window-row";
            target_row.appendChild(createPlayer(target.path, target.id));
            const add_btn = document.createElement("div");
            add_btn.className = "smm-add-btn";
            add_btn.textContent = "+";
            add_btn.addEventListener("click", () => {
                const add_window = document.querySelector(".overlay .add-voice-window");
                if (add_window) {
                    add_window.dataset.path = target.path;
                    add_window.querySelector("#add-voice-name").value = "";
                    add_window.querySelector("#add-voice-desc").value = "";
                    add_window.classList.add("open");
                }
            });
            target_row.appendChild(add_btn);
        }
        fragment.appendChild(target_row);
    });
    if (isFavorite) {
        targets_list.innerHTML = "";
        fragment
            .querySelector(".dialog-title")
            ?.insertAdjacentHTML("afterbegin", `<div class="favorite-icon">★</div>`);
        const load_more_btn = document.createElement("div");
        load_more_btn.className = "btn";
        load_more_btn.textContent = "Загрузить еще";
        load_more_btn.addEventListener("click", async () => {
            load_more_btn.remove();
            targets_list.insertAdjacentHTML("beforeend", makeProgressBar());
            // setTimeout(async () => {
            await bridge.get_session_dialogs(target_id_str, session_file, false);
            // }, 4000);
        });
        fragment.appendChild(load_more_btn);
    }
    targets_list.appendChild(fragment);
}

function closeModalWindow() {
    document.getElementById("overlay")?.classList.toggle("open", false);
    stopPlay();
}

async function authorizeToSession() {
    const phone_number_input = document
        .getElementById("auth-phone-input")
        .value.trim();
    await bridge.saveSession("", "", phone_number_input);
}

async function addSessions(elem) {
    const sessions_list = document.getElementById("sessions-list");
    if (!sessions_list) return;

    const file = elem.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = async function(e) {
            const base64data = e.target.result.split(",")[1];
            await bridge.saveSession(file.name, base64data, "");
            elem.value = "";
        };
        reader.readAsDataURL(file);
    }
}

async function deleteSession(elem) {
    const row = elem.closest(".row");
    const session_id = String(row.dataset.id);
    const session_name = row.querySelector(".session-name").innerText;

    await bridge.deleteSession(session_id, session_name);
}

function removeSessionRow(session_id) {
    document
        .querySelector(`#sessions-list .row[data-id="${session_id}"]`)
        ?.remove();
}

async function startSession(elem) {
    const session = elem.closest(".row");
    const session_id = session.dataset.id;
    const session_name = session.querySelector(".session-name").innerText;
    await bridge.startSession(
        JSON.stringify({ session_id: session_id, session_name: session_name }),
    );

    elem.closest(".buttons").innerHTML = `
        <div class="btn" style="background-color: blue;"><div class="loader"></div></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
    `;
}

function sessionChangedState(session_id, state) {
    const session_divs = document.querySelectorAll(
        ".sessions .sessions-list .row",
    );
    session_divs.forEach((session_row) => {
        if (session_row.dataset.id === session_id) {
            const buttons = session_row.querySelector(".buttons");
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
    const session = elem.closest(".row");
    const session_name = session.querySelector(".session-name").innerText;
    await bridge.stopSession(session_name);

    elem.closest(".buttons").innerHTML = `
        <div class="btn" style="background-color: blue;"><div class="loader"></div></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
    `;
}

async function renderSMMMessages(smm_messages_str) {
    const smm_list = document.getElementById("smm-message-list");
    if (!smm_list) return;

    let last_index = -1;
    if (smm_list.innerHTML !== "")
        last_index = Number(
            smm_list.lastChild.querySelector(".index").innerText.slice(0, -1),
        );

    const fragment = document.createDocumentFragment();
    const smm_messages = JSON.parse(smm_messages_str);
    smm_messages.forEach((smm_message, index) => {
        const row = document.createElement("div");
        row.classList = "row";
        row.dataset.id = smm_message.id;
        row.innerHTML = `
            <div class="row-content">
                <div class="left-smm-side">
                    <div class="index">${last_index === -1 ? index + 1 : last_index + 1}.</div>
                    <textarea class="smm-text" disabled>${smm_message.text || ""}</textarea>
                    <label>
                        <img class="image-preview" src="${smm_message.photo ? "../assets/smm_images/" + smm_message.photo : "assets/images/add_image.png"}" alt="add image" onclick="openImage(this)">
                        <input type="file" accept=".jpg,.jpeg,.png" onchange="uploadImage(this)" disabled>
                    </label>
                </div>
                <div class="buttons">
                    <div class="btn edit-btn"><img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editMessage(this)"></div>
                    <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteMessage(this)"></div>
                </div>
            </div>
        `;
        fragment.appendChild(row);
    });
    smm_list.appendChild(fragment);
}

async function uploadImage(elem) {
    const img = elem.parentElement.querySelector("img");
    const file = elem.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64data = e.target.result.split(",")[1];
            img.src = e.target.result;
            img.dataset.base64 = base64data;
            img.dataset.filename = file.name;
            elem.value = "";
        };
        reader.readAsDataURL(file);
    }
}

async function addSMMMessage() {
    const textarea = document.getElementById("newMessage");
    const img = document.getElementById("newPhoto");

    if (textarea.value === "" && !img.dataset.base64) return;

    const newSMMMessage = {
        text: textarea.value || null,
        photo: img.dataset.base64 || null,
        filename: img.dataset.filename || null,
    };

    await bridge.addNewSMMMessage(JSON.stringify(newSMMMessage));

    textarea.value = "";
    img.src = "assets/images/add_image.png";
    delete img.dataset.base64;
    delete img.dataset.filename;
}

async function deleteMessage(elem) {
    const row = elem.closest(".row");
    const smm_message_id = row.dataset.id;
    await bridge.deleteSMMMessage(String(smm_message_id));

    row.remove();
}

function openImage(elem) {
    if (
        elem.src.includes("add_image.png") ||
        temp_text !== "" ||
        temp_photo !== ""
    )
        return;

    const overlay = document.getElementById("image-preview-overlay");
    const fullimg = document.getElementById("image-preview-fullscreen");
    fullimg.src = elem.src;
    overlay.style.display = "flex";
}

function editMessage(elem) {
    const row = elem.closest(".row");
    const textarea = row.querySelector("textarea");
    const img_preview = row.querySelector(".image-preview");
    const input_elem = row.querySelector("input");
    const buttons = row.querySelector(".buttons");

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
    const row = elem.closest(".row");
    const textarea = row.querySelector("textarea");
    const img_preview = row.querySelector(".image-preview");
    const input_elem = row.querySelector("input");
    const buttons = row.querySelector(".buttons");

    textarea.value = temp_text;
    textarea.disabled = true;
    img_preview.src = temp_photo;
    input_elem.disabled = true;
    buttons.innerHTML = `
        <div class="btn edit-btn"><img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editMessage(this)"></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteMessage(this)"></div>
    `;

    temp_photo = "";
    temp_text = "";
    delete img_preview.dataset.base64;
    delete img_preview.dataset.filename;
}

async function saveChanges(elem) {
    const row = elem.closest(".row");
    const textarea = row.querySelector("textarea");
    const img_preview = row.querySelector(".image-preview");

    if (textarea.value === temp_text && !img_preview.dataset.base64) {
        discardChanges(elem);
        return;
    }

    const editedSMM = {
        id: String(row.dataset.id),
        text: textarea.value || null,
        photo: img_preview.dataset.base64 || null,
        filename: img_preview.dataset.filename || null,
    };

    await bridge.saveChanges(JSON.stringify(editedSMM));

    const input_elem = row.querySelector("input");
    const buttons = row.querySelector(".buttons");
    textarea.disabled = true;
    input_elem.disabled = true;
    buttons.innerHTML = `
        <div class="btn edit-btn"><img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editMessage(this)"></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteMessage(this)"></div>
    `;

    temp_photo = "";
    temp_text = "";
    delete img_preview.dataset.base64;
    delete img_preview.dataset.filename;
}

function changeMailingType(type) {
    const select_block = document.querySelector(".select-mailing-type");
    if (type === "usernames") {
        select_block
            .querySelector("#mailing-database")
            .classList.remove("active-type");
        select_block
            .querySelector("#mailing-usernames")
            .classList.add("active-type");
    } else if (type === "db") {
        select_block
            .querySelector("#mailing-usernames")
            .classList.remove("active-type");
        select_block
            .querySelector("#mailing-database")
            .classList.add("active-type");
    }
}

function changeMessageType(type) {
    const select_block = document.querySelector(".select-message-type");
    if (type === "text") {
        select_block
            .querySelector("#voice-message")
            .classList.remove("active-type");
        select_block
            .querySelector("#text-message")
            .classList.add("active-type");
    } else if (type === "voice") {
        select_block
            .querySelector("#text-message")
            .classList.remove("active-type");
        select_block
            .querySelector("#voice-message")
            .classList.add("active-type");
    }
}

function changeParsingType(type) {
    const select_block = document.querySelector(".select-parse-type");
    if (type === "channel") {
        select_block.querySelector("#parse-group").classList.remove("active-type");
        select_block.querySelector("#parse-channel").classList.add("active-type");
        document.getElementById("parse-group-settings").style.display = "none";
        document.getElementById("parse-channel-settings").style.display = "flex";
    } else if (type === "group") {
        select_block
            .querySelector("#parse-channel")
            .classList.remove("active-type");
        select_block.querySelector("#parse-group").classList.add("active-type");
        document.getElementById("parse-channel-settings").style.display = "none";
        document.getElementById("parse-group-settings").style.display = "flex";
    }
}

function changeGroupParseSettings(type) {
    const select_block = document.querySelector(".parse-group-settings");
    if (type === "messages") {
        select_block
            .querySelector("#parse-group-participants")
            .classList.remove("active-type");
        select_block
            .querySelector("#parse-group-messages")
            .classList.add("active-type");
        document.getElementById("messages-parse-settings").style.display = "flex";
    } else if (type === "participants") {
        select_block
            .querySelector("#parse-group-messages")
            .classList.remove("active-type");
        select_block
            .querySelector("#parse-group-participants")
            .classList.add("active-type");
        document.getElementById("messages-parse-settings").style.display = "none";
    }
}

async function loadChooseSessions() {
    await bridge.loadChooseSessions();
}

function renderChooseSessions(sessions_str) {
    const isChecked = (sessId) => {
        if (
            openedSettingsTabName === "mailing" &&
            Boolean(selectedMailSessions?.[sessId]) &&
            "checked"
        ) {
            return "checked";
        }
        if (
            openedSettingsTabName === "parsing" &&
            Boolean(selectedParseSessions?.[sessId]) &&
            "checked"
        ) {
            return "checked";
        }
        return null;
    };
    const sessions = JSON.parse(sessions_str);
    const modal = document.getElementById("session-modal");
    const sessionList = document.getElementById("session-list");
    sessionList.innerHTML = "";

    sessions.forEach((session) => {
        const div = document.createElement("div");
        div.innerHTML = `
            <label>
                <input
                    type="checkbox"
                    value="${session.session_id}"
                    class="session-checkbox"
                    data-file="${session.session_file}"
                    ${isChecked(session.session_id)}
                >
                ${session.session_file}
            </label>
        `;
        sessionList.appendChild(div);
    });

    modal.classList.remove("hidden");
}

function closeSessionModal() {
    document.getElementById("session-modal").classList.add("hidden");
}

function confirmSelectedSessions() {
    if (openedSettingsTabName === "mailing") {
        // обнуляем объект с сохраненными сессиями
        selectedMailSessions = {};
        document.querySelectorAll(".session-checkbox:checked").forEach((cb) => {
            const session_id = parseInt(cb.value, 10);
            const session_file = cb.dataset.file;
            selectedMailSessions[session_id] = session_file;
        });
        const count = Object.keys(selectedMailSessions).length;
        document.getElementById("mailing-account-count").innerText = String(count);
        closeSessionModal();
    }
    if (openedSettingsTabName === "parsing") {
        // обнуляем объект с сохраненными сессиями
        selectedParseSessions = {};
        document.querySelectorAll(".session-checkbox:checked").forEach((cb) => {
            const session_id = parseInt(cb.value, 10);
            const session_file = cb.dataset.file;
            selectedParseSessions[session_id] = session_file;
        });
        const count = Object.keys(selectedParseSessions).length;
        document.getElementById("parse-account-count").innerText = String(count);
        closeSessionModal();
    }
}

async function startParsing() {
    const parse_links = document.getElementById("parse-links").value.trim();
    const is_parse_channel = document
        .getElementById("parse-channel")
        .classList.contains("active-type");
    const count_of_posts = document.getElementById("posts-parse-count").value;
    const is_parse_messages = document
        .getElementById("parse-group-messages")
        .classList.contains("active-type");
    const count_of_messages = document.getElementById(
        "messages-parse-count",
    ).value;

    if (
        !selectedParseSessions ||
        selectedParseSessions.length === 0 ||
        !parse_links ||
        (is_parse_channel && !count_of_posts) ||
        (!is_parse_channel && is_parse_messages && !count_of_messages)
    ) {
        bridge.show_notification("Введите корректные данные");
        return;
    }

    const parse_data = {
        parse_links,
        is_parse_channel,
        count_of_posts,
        is_parse_messages,
        count_of_messages,
        selected_sessions: selectedParseSessions,
    };
    await bridge.startParsing(JSON.stringify(parse_data));
}

async function stopParsing() {
    await bridge.stopParsing();
}

function renderParsingProgressData(render_data_str) {
    const render_data = JSON.parse(render_data_str);
    const stop_button = document.getElementById("stop-parsing-button");
    const start_button = document.getElementById("start-parsing-button");
    const save_db_button = document.getElementById("save-results-to-computer");
    const export_csv_button = document.getElementById("add-results-to-database");
    if (stop_button.disabled) stop_button.disabled = false;
    if (!start_button.disabled) start_button.disabled = true;
    if (!save_db_button.disabled) save_db_button.disabled = true;
    if (!export_csv_button.disabled) export_csv_button.disabled = true;
    document.getElementById("parsing-status").innerText = render_data.status;
    document.getElementById("total-parsed-count").innerText =
        render_data.total_count;
    document.getElementById("current-chat").innerText = render_data.chat;
    document.getElementById("parsing-elapsed-time").innerText =
        render_data.elapsed_time;
}

function finishParsing() {
    document.getElementById("parsing-status").innerText = "завершено";
    document.getElementById("start-parsing-button").disabled = false;
    document.getElementById("stop-parsing-button").disabled = true;
    document.getElementById("save-results-to-computer").disabled = false;
    document.getElementById("add-results-to-database").disabled = false;
}

async function saveToDB() {
    await bridge.saveParsedData("db");
}

async function exportCSV() {
    await bridge.saveParsedData("csv");
}

async function startMailing() {
    const is_parse_usernames = document
        .getElementById("mailing-usernames")
        .classList.contains("active-type");
    const is_send_text = document
        .getElementById("text-message")
        .classList.contains("active-type");
    const mailing_data = document
        .getElementById("mailing-data-field")
        .value.trim();
    const delay = document.getElementById("delay-between-mailing-messages").value;

    if (is_parse_usernames && !mailing_data) {
        bridge.show_notification("Введите данные для рассылки");
        return;
    }

    const mail_data = {
        is_parse_usernames,
        is_send_text,
        mailing_data,
        delay,
        selected_sessions: selectedMailSessions,
    };

    await bridge.startMailing(JSON.stringify(mail_data));
}

async function stopMailing() {
    await bridge.stopMailing();
}

function renderMailingProgressData(render_data_str) {
    const render_data = JSON.parse(render_data_str);
    const start_button = document.getElementById("start-mailing-button");
    const stop_button = document.getElementById("stop-mailing-button");
    if (!start_button.disabled) start_button.disabled = true;
    if (stop_button.disabled) stop_button.disabled = false;
    document.getElementById("mailing-status").innerText = render_data.status;
    document.getElementById("total-mailed-count").innerText =
        render_data.total_count;
    document.getElementById("mailing-time").innerText = render_data.time;
}

function finishMailing() {
    document.getElementById("mailing-status").innerText = "завершено";
    document.getElementById("start-mailing-button").disabled = false;
    document.getElementById("stop-mailing-button").disabled = true;
}

function renderSettings(settings_str) {
    const settings = JSON.parse(settings_str);

    for (const [key, value] of Object.entries(settings)) {
        const elem = document.getElementById(key.replaceAll("_", "-"));

        if (!elem) continue;

        if (elem.type === "checkbox") {
            elem.checked = Boolean(value);
        } else {
            elem.value = value;
        }
    }
}

function changeSettings(elem) {
    const elem_type = elem.type;
    const key = elem.name;
    let value = null;
    if (elem_type === "checkbox") {
        value = elem.checked;
    } else if (elem_type === "text") {
        if (key === "api_keys")
            if (/^\d{5,8}\:[a-fA-F0-9]{32}$/.test(elem.value)) value = elem.value;
            else {
                bridge.show_notification("Неверные ключи");
                return;
            }
    }

    bridge.changeSettings(JSON.stringify({ key, value }));
}

async function refreshSessionManager() {
    await bridge.refreshSessionManager();
}

function resetSettings() {
    bridge.resetSettings();
}
