let bridge = null;
let temp_text = "";
let temp_photo = "";
let selectedParseSessions = {};
let selectedMailSessions = {};
let sessionGroupSelections = {};
let sessionsList = [];
let openedSettingsTabName = undefined;

// Pudge state
let pudgeConfigs = {};        // session_id → {send_to_saved, target_group, hook_ids}
let allHookMessages = [];     // full list from DB, used for hooks modal
let currentPudgeHooksSessionId = null;
let _pudgeGroupInputTimers = {};
let pudgeDefaultGroup = "";
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
    bridge.renderMailingLinks.connect(renderMailingLinks);
    bridge.changeGroupMailingStatus.connect(changeGroupMailingStatus);
    bridge.updateGroupMailingProgress.connect(updateGroupMailingProgress);
    bridge.updateGroupMailingRetry.connect(updateGroupMailingRetry);
    bridge.sessionGroupsStatus.connect(sessionGroupsStatus);
    bridge.renderSessionGroups.connect(renderSessionGroups);
    bridge.parsedActionResult.connect(parsedActionResult);
    bridge.renderHookMessages.connect(renderHookMessages);
    bridge.changePudgeStatus.connect(changePudgeStatus);
    bridge.updatePudgeReceivedCount.connect(updatePudgeReceivedCount);
    bridge.pudgeCheckResult.connect(handlePudgeCheckResult);
    bridge.renderPudgeSessionGroups.connect(renderPudgeSessionGroups);
    bridge.pudgeGroupsStatus.connect(pudgeGroupsStatus);
    bridge.renderPudgeLinks.connect(renderPudgeLinks);
    bridge.renderPudgeDefaultGroup.connect(setRenderPudgeDefaultGroup);
});

document.addEventListener("keyup", (event) => {
    if (event.key === "Escape") {
        const confirmModal = document.getElementById("confirm-action-modal");
        if (confirmModal && !confirmModal.classList.contains("hidden")) {
            return closeConfirmActionModal();
        }
        const groupModal = document.getElementById("links-modal");
        if (groupModal && !groupModal.classList.contains("hidden")) {
            return groupModal.classList.add("hidden");
        }
        const linksModal = document.getElementById("mailing-links-modal");
        if (linksModal && !groupModal.classList.contains("hidden")) {
            return linksModal.classList.add("hidden");
        }
        const sessionModal = document.getElementById("session-modal");
        if (sessionModal && !sessionModal.classList.contains("hidden")) {
            return sessionModal.classList.add("hidden");
        }
        const pudgeHooksModal = document.getElementById("pudge-hooks-modal");
        if (pudgeHooksModal && !pudgeHooksModal.classList.contains("hidden")) {
            return closePudgeHooksModal();
        }
        const pudgeLinksModal = document.getElementById("pudge-links-modal");
        if (pudgeLinksModal && !pudgeLinksModal.classList.contains("hidden")) {
            return closePudgeLinksModal();
        }
    }
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

    if (tab_name === "pudge") {
        document.getElementById("pudge-tab").classList.add("active-tab");
        document.getElementById("pudge-tab-block").classList.add("active-tab-block");
        document.querySelector("#pudge-session-container-block .sessions-list").innerHTML = "";
        await bridge.loadSessions("pudge");
        await bridge.loadHookMessages();
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
        await bridge.loadSessions("settings");
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
        .querySelector("#smm-tab-block .sub-block.active-tab-block")
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
    } else if (tab_name === "hooks") {
        document.getElementById("hooks-tab").classList.add("active-tab");
        document.getElementById("hooks-smm-block").classList.add("active-tab-block");
        document.getElementById("hook-message-list").innerHTML = "";
        await bridge.loadHookMessages();
    }
}

async function openMailingSettingsTab(tab_name) {
    document
        .querySelector(".mailing-tabs .tab.active-tab")
        ?.classList.remove("active-tab");

    document
        .querySelector("#mailing-tab-block .sub-block.active-tab-block")
        ?.classList.remove("active-tab-block");

    if (tab_name === "user") {
        document.getElementById("user-mailing-tab").classList.add("active-tab");
        document
            .getElementById("user-mailing-block")
            .classList.add("active-tab-block");
    } else if (tab_name === "group") {
        document.getElementById("group-mailing-tab").classList.add("active-tab");
        document
            .getElementById("group-mailing-block")
            .classList.add("active-tab-block");
        document.querySelector(
            "#mailing-session-container-block .sessions-list",
        ).innerHTML = "";
        await bridge.loadSessions("mailing");
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
        await bridge.loadSessions("voices");
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

async function renderSessions(sessions_json, destination) {
    if (destination === "pudge") {
        renderPudgeSessions(sessions_json);
        return;
    }

    let container_id = null;

    if (destination === "settings") {
        container_id = "#sessions-tab-block";
    } else if (destination === "voices") {
        container_id = "#smm-session-container-block";
    } else if (destination === "mailing") {
        container_id = "#mailing-session-container-block";
    }

    if (!container_id) {
        return;
    }

    const sessions_list = document.querySelector(
        `${container_id} .sessions-list`,
    );

    if (!sessions_list) return;

    const fragment = document.createDocumentFragment();
    const sessions = JSON.parse(sessions_json);
    sessions.forEach((session) => {
        const row = document.createElement("div");
        row.className = "row";
        row.dataset.id = session.session_id;
        row.innerHTML = `
            <div class="session-avatar-wrap">
                <div class="session-avatar-inner">${_buildSessionAvatar(session)}</div>
            </div>
            <div class="row-content">
                <div class="session-info">
                    Сессия: <span class="session-name">${session.session_file}</span> Номер телефона: <span class="session-phone">${session.phone_number}</span>
                </div>
            </div>
        `;

        if (destination === "settings") {
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
        } else if (destination === "voices") {
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
        } else if (destination === "mailing") {
            let controlButton = "";
            if (session.groupMailing) {
                controlButton =
                    '<div class="btn stop-group-mailing" onclick="toggleControlGroupMailing(false, this)">Стоп</div>';
            } else {
                controlButton =
                    '<div class="btn start-group-mailing" onclick="toggleControlGroupMailing(true, this)">Начать</div>';
            }

            row.querySelector(".row-content").insertAdjacentHTML(
                "beforeend",
                `
                    <div class="group-mailing-info">
                        <div class="mailing-delay-label">
                            <span>Задержка, сек</span>
                            <input type="number" placeholder="0" class="input-number group-mailing-delay" oninput="this.value = this.value.replace(/[^0-9]/g, '').slice(0, 6);">
                        </div>
                        <div>Отправлено: <span class="group-mailing-count">0</span></div>
                        <div>Последнее в: <span class="group-mailing-time">—</span></div>
                        <div class="group-mailing-retry" style="display:none"></div>
                    </div>
                    <div class="buttons">
                        <div class="btn open-groups" onclick="openLinksModal(this)">Группы</div>
                        <div class="btn open-groups" onclick="loadMailingLinks(this)">Ссылки</div>
                        ${controlButton}
                    </div>
                `,
            );
        }
        fragment.appendChild(row);
    });
    sessions_list.appendChild(fragment);
}

function updateGroupMailingProgress(session_id, count, last_time) {
    const row = document.querySelector(
        `#mailing-session-container-block .row[data-id="${session_id}"]`,
    );
    if (!row) return;
    const countEl = row.querySelector(".group-mailing-count");
    const timeEl = row.querySelector(".group-mailing-time");
    if (countEl) countEl.textContent = String(count);
    if (timeEl) timeEl.textContent = last_time;
}

const _retryTimers = {};

function _formatCountdown(seconds) {
    const m = String(Math.floor(seconds / 60)).padStart(2, "0");
    const s = String(seconds % 60).padStart(2, "0");
    return `${m}:${s}`;
}

function updateGroupMailingRetry(session_id, attempt, max_attempts, wait_seconds) {
    const row = document.querySelector(
        `#mailing-session-container-block .row[data-id="${session_id}"]`,
    );
    if (!row) return;

    if (_retryTimers[session_id]) {
        clearInterval(_retryTimers[session_id]);
        delete _retryTimers[session_id];
    }

    const retryEl = row.querySelector(".group-mailing-retry");
    if (!retryEl) return;

    if (attempt === 0) {
        retryEl.style.display = "none";
        retryEl.textContent = "";
        return;
    }

    retryEl.style.display = "";
    let remaining = wait_seconds;

    const update = () => {
        retryEl.textContent = `Попытка: ${attempt}/${max_attempts} Время: ${_formatCountdown(remaining)}`;
    };
    update();

    _retryTimers[session_id] = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(_retryTimers[session_id]);
            delete _retryTimers[session_id];
            retryEl.textContent = `Попытка: ${attempt}/${max_attempts} Подключение...`;
            return;
        }
        update();
    }, 1000);
}

function changeGroupMailingStatus(session_id, is_on) {
    const controlButtons = document.querySelector(
        `#mailing-session-container-block .row[data-id="${session_id}"] .buttons`,
    );

    if (!controlButtons) {
        return;
    }

    controlButtons.querySelector(".mailing-loader")?.remove();

    if (is_on) {
        controlButtons.querySelector(".start-group-mailing")?.remove();
        controlButtons.insertAdjacentHTML(
            "beforeend",
            '<div class="btn stop-group-mailing" onclick="toggleControlGroupMailing(false, this)">Стоп</div>',
        );
    } else {
        updateGroupMailingRetry(session_id, 0, 0, 0);
        controlButtons.querySelector(".stop-group-mailing")?.remove();
        controlButtons.insertAdjacentHTML(
            "beforeend",
            '<div class="btn start-group-mailing" onclick="toggleControlGroupMailing(true, this)">Начать</div>',
        );
    }
}

async function toggleControlGroupMailing(is_start, elem) {
    const row = elem.closest(".row");
    if (!row) return;
    const session_id = row.dataset.id;
    if (!session_id) return;
    if (elem.dataset.pending) return;

    elem.outerHTML = `<div class="btn mailing-loader" style="background-color: blue;"><div class="loader"></div></div>`;

    if (is_start) {
        let delay = row.querySelector(".group-mailing-delay")?.value || 0;
        await bridge.startGroupMailing(session_id, delay);
    } else {
        await bridge.stopGroupMailing(session_id);
    }
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
            else if (state === "needs_reauth")
                buttons.innerHTML = `
                    <input type="text" class="input-number reauth-phone" placeholder="Телефон"
                        maxlength="16" oninput="this.value = this.value.replace(/\\D/g, '').slice(0, 16);"
                        style="width: 115px;">
                    <div class="btn start-session-btn" onclick="reauthorizeSession(this)">Войти</div>
                    <div class="btn open-groups" onclick="reauthorizeSession(this, true)">QR</div>
                    <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
                `;
            return;
        }
    });
}

async function reauthorizeSession(elem, useQR = false) {
    const row = elem.closest(".row");
    const session_id = row.dataset.id;
    const session_name = row.querySelector(".session-name").innerText;
    const phone = useQR ? "" : (row.querySelector(".reauth-phone")?.value.trim() || "");

    row.querySelector(".buttons").innerHTML = `
        <div class="btn" style="background-color: blue;"><div class="loader"></div></div>
        <div class="btn delete-btn"><img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteSession(this)"></div>
    `;

    await bridge.reauthorizeSession(JSON.stringify({ session_id, session_name, phone }));
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
                    <label class="label-image-preview">
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
        document.getElementById("mailing-order-block").style.display = "none";
    } else if (type === "db") {
        select_block
            .querySelector("#mailing-usernames")
            .classList.remove("active-type");
        select_block
            .querySelector("#mailing-database")
            .classList.add("active-type");
        document.getElementById("mailing-order-block").style.display = "";
    }
}

function changeMessageType(type) {
    const select_block = document.querySelector(".select-message-type");
    if (type === "text") {
        select_block
            .querySelector("#voice-message")
            .classList.remove("active-type");
        select_block.querySelector("#text-message").classList.add("active-type");
    } else if (type === "voice") {
        select_block.querySelector("#text-message").classList.remove("active-type");
        select_block.querySelector("#voice-message").classList.add("active-type");
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
        const checked = isChecked(session.session_id) === "checked";
        div.className = "session-row-item" + (checked ? " selected" : "");
        const showGroupsBtn = openedSettingsTabName === "parsing";
        const groupCount = (sessionGroupSelections[session.session_id] || []).length;
        const groupBtnLabel = groupCount > 0 ? `Группы (${groupCount})` : "Группы";
        div.innerHTML = `
            <label class="choose-session-label">
                <div class="session-avatar-wrap session-avatar-sm">
                    <div class="session-avatar-inner">${_buildSessionAvatar(session)}</div>
                    <div class="session-avatar-check">✓</div>
                </div>
                <input
                    type="checkbox"
                    value="${session.session_id}"
                    class="session-checkbox"
                    data-file="${session.session_file}"
                    ${isChecked(session.session_id)}
                    hidden
                >
                <span>${session.session_file}</span>
            </label>
            ${showGroupsBtn ? `<button class="btn parse-groups-btn" data-session-id="${session.session_id}" onclick="openParseGroupsModal(${session.session_id}, '${session.session_file}')">${groupBtnLabel}</button>` : ""}
        `;
        const cb = div.querySelector(".session-checkbox");
        cb.addEventListener("change", () => {
            div.classList.toggle("selected", cb.checked);
        });
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

async function loadMailingLinks(button) {
    const row = button.closest(".row");
    await bridge.loadMailingLinks(row.dataset.id);
}

function renderMailingLinks(session_id, groups_data_str) {
    const modal = document.getElementById("mailing-links-modal");
    if (!modal) return;

    modal.dataset.id = session_id;
    modal.querySelector("textarea").value = groups_data_str;
    modal?.classList.remove("hidden");
}

async function confirmMailingLinks() {
    const modal = document.getElementById("mailing-links-modal");
    if (!modal) return closeMailingLinksModal();

    const groups_data = modal.querySelector("textarea").value;
    await bridge.updateMailingLinks(modal.dataset.id, groups_data);

    closeMailingLinksModal();
}

function closeMailingLinksModal() {
    const modal = document.getElementById("mailing-links-modal");
    if (!modal) return;

    modal.dataset.id = "";
    modal.classList.add("hidden");
}

function _setLinksConfirmEnabled(enabled) {
    const btn = document.querySelector("#links-modal .accept-btn");
    if (!btn) return;
    btn.classList.toggle("disabled", !enabled);
}

async function openParseGroupsModal(sessionId, sessionFile) {
    const modal = document.getElementById("links-modal");
    if (!modal) return;

    modal.dataset.id = String(sessionId);
    modal.dataset.file = sessionFile;
    modal.dataset.context = "parsing";
    modal.dataset.fetchedIds = "[]";
    document.getElementById("links-list").innerHTML = "";
    document.getElementById("links-search").value = "";
    document.getElementById("links-select-all").checked = false;
    filterLinks("");
    const statusEl = document.getElementById("links-modal-status");
    if (statusEl) statusEl.textContent = "Загрузка...";
    _setLinksConfirmEnabled(false);
    modal.classList.remove("hidden");

    await bridge.loadSessionGroups(String(sessionId), sessionFile);
}

async function openLinksModal(button) {
    const row = button.closest(".row");
    const modal = document.getElementById("links-modal");
    if (!modal) return;

    const session_id = row.dataset.id;
    const session_file = row.querySelector(".session-name").innerText;

    modal.dataset.id = session_id;
    modal.dataset.file = session_file;
    modal.dataset.context = "mailing";
    modal.dataset.fetchedIds = "[]";
    document.getElementById("links-list").innerHTML = "";
    document.getElementById("links-search").value = "";
    document.getElementById("links-select-all").checked = false;
    filterLinks("");
    const statusEl = document.getElementById("links-modal-status");
    if (statusEl) statusEl.textContent = "Загрузка...";
    _setLinksConfirmEnabled(false);
    modal.classList.remove("hidden");

    await bridge.loadSessionGroups(session_id, session_file);
}

function sessionGroupsStatus(session_id, status) {
    const modal = document.getElementById("links-modal");
    if (!modal || modal.dataset.id !== String(session_id)) return;
    const statusEl = document.getElementById("links-modal-status");
    if (statusEl) statusEl.textContent = status;
}

function _getGroupColor(name) {
    const palette = ["#4d6af5","#e05c5c","#3faa6e","#c97b3f","#9b59b6","#2980b9","#16a085","#d35400"];
    let h = 0;
    for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
    return palette[Math.abs(h) % palette.length];
}

function _buildEntityTypeIcon(entityType) {
    if (entityType === "channel") {
        return `<svg class="links-item-type-icon" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M18 11v2h4v-2h-4zm-2 6.61c.96.71 2.21 1.65 3.2 2.39.4-.53.8-1.07 1.2-1.61-.99-.74-2.24-1.68-3.2-2.4-.4.54-.8 1.08-1.2 1.62zM20.4 5.6c-.4-.54-.8-1.07-1.2-1.6-.96.74-2.24 1.65-3.2 2.4.4.53.8 1.07 1.2 1.6.96-.74 2.24-1.65 3.2-2.4zM4 9c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h1v4h2v-4h1l5 3V6L8 9H4zm11.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>`;
    }
    return `<svg class="links-item-type-icon" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>`;
}

function _buildSessionAvatar(session) {
    if (session.avatar) {
        return `<img src="../assets/session_photos/${session.session_file}/${session.avatar}" alt="">`;
    }
    const color = _getGroupColor(session.session_file || "?");
    const label = (session.session_file || "?").charAt(0).toUpperCase();
    return `<div class="session-avatar-placeholder" style="background:${color}">${label}</div>`;
}

function _buildGroupPhoto(g, sessionFile) {
    if (g.photo_type === "image") {
        return `<img src="../assets/group_photos/${sessionFile}/${g.photo}" alt="">`;
    }
    const color = _getGroupColor(g.title);
    const label = g.photo_type === "gif"
        ? `<span style="font-size:10px;font-weight:700;letter-spacing:0.5px">GIF</span>`
        : g.title.charAt(0).toUpperCase();
    return `<div class="links-item-placeholder" style="background:${color}">${label}</div>`;
}

function toggleLinksItem(item) {
    const cb = item.querySelector("input[type='checkbox']");
    if (!cb) return;
    cb.checked = !cb.checked;
    item.classList.toggle("selected", cb.checked);
    const allCbs = [...document.querySelectorAll("#links-list input[type='checkbox']")];
    document.getElementById("links-select-all").checked =
        allCbs.length > 0 && allCbs.every(c => c.checked);
}

function renderSessionGroups(session_id, groups_json) {
    const modal = document.getElementById("links-modal");
    if (!modal || modal.dataset.id !== String(session_id)) return;

    const groups = JSON.parse(groups_json);
    if (modal.dataset.context === "parsing") {
        const prevSelected = new Set(sessionGroupSelections[session_id] || []);
        groups.forEach(g => { g.selected = prevSelected.has(g.identifier); });
    }
    const sessionFile = modal.dataset.file || "";
    modal.dataset.fetchedIds = JSON.stringify(groups.map(g => g.identifier));

    const list = document.getElementById("links-list");
    list.innerHTML = "";

    if (groups.length === 0) {
        list.innerHTML = '<div class="links-empty-msg">Нет групп или каналов</div>';
        _setLinksConfirmEnabled(false);
        const statusEl = document.getElementById("links-modal-status");
        if (statusEl) statusEl.textContent = "";
        return;
    }

    const fragment = document.createDocumentFragment();
    groups.forEach(g => {
        const item = document.createElement("div");
        item.className = "links-item" + (g.selected ? " selected" : "");
        item.onclick = () => toggleLinksItem(item);
        item.innerHTML = `
            <div class="links-item-photo">
                <div class="links-item-photo-inner">
                    ${_buildGroupPhoto(g, sessionFile)}
                </div>
                <div class="links-item-check">✓</div>
            </div>
            <div class="links-item-info">
                ${_buildEntityTypeIcon(g.entity_type)}
                <span class="links-item-name">${g.title}</span>
            </div>
            <input type="checkbox" value="${g.identifier}" ${g.selected ? "checked" : ""} hidden>
        `;
        fragment.appendChild(item);
    });
    list.appendChild(fragment);

    const allChecked = groups.every(g => g.selected);
    document.getElementById("links-select-all").checked = allChecked;

    const statusEl = document.getElementById("links-modal-status");
    if (statusEl) statusEl.textContent = "";
    _setLinksConfirmEnabled(true);
}

async function confirmLinksSelection() {
    const modal = document.getElementById("links-modal");
    if (!modal) return closeLinksModal();

    const session_id = modal.dataset.id;
    const context = modal.dataset.context;
    const fetchedIds = JSON.parse(modal.dataset.fetchedIds || "[]");
    const checked = [...document.querySelectorAll("#links-list input[type='checkbox']:checked")]
        .map(cb => cb.value);

    if (context === "parsing") {
        sessionGroupSelections[session_id] = checked;
        const btn = document.querySelector(`.parse-groups-btn[data-session-id="${session_id}"]`);
        if (btn) btn.textContent = checked.length > 0 ? `Группы (${checked.length})` : "Группы";
        closeLinksModal();
        return;
    }

    if (context === "pudge") {
        await bridge.updatePudgeGroups(session_id, JSON.stringify({
            fetched: fetchedIds,
            selected: checked,
        }));
        closeLinksModal();
        return;
    }

    await bridge.updateSessionGroups(session_id, JSON.stringify({
        fetched: fetchedIds,
        selected: checked,
    }));
    closeLinksModal();
}

function closeLinksModal() {
    const modal = document.getElementById("links-modal");
    if (!modal) return;

    modal.dataset.id = "";
    modal.classList.add("hidden");
}

function filterLinks(query) {
    const list = document.getElementById("links-list");
    if (!list) return;

    const q = query.toLowerCase();
    list.querySelectorAll(".links-item").forEach(item => {
        const nameEl = item.querySelector(".links-item-name");
        item.style.display =
            !q || (nameEl && nameEl.textContent.toLowerCase().includes(q)) ? "" : "none";
    });
}

function toggleAllLinks(checkbox) {
    const list = document.getElementById("links-list");
    if (!list) return;

    list.querySelectorAll(".links-item").forEach(item => {
        const cb = item.querySelector("input[type='checkbox']");
        if (cb) cb.checked = checkbox.checked;
        item.classList.toggle("selected", checkbox.checked);
    });
}

async function startParsing() {
    const parse_links = document.getElementById("parse-links").value.trim();
    const count_of_posts = document.getElementById("posts-parse-count").value;
    const is_parse_messages = document
        .getElementById("parse-group-messages")
        .classList.contains("active-type");
    const count_of_messages = document.getElementById(
        "messages-parse-count",
    ).value;

    const session_groups = {};
    for (const [sid, groups] of Object.entries(sessionGroupSelections)) {
        if (groups.length > 0) session_groups[sid] = groups;
    }
    const hasSessionGroups = Object.values(session_groups).some(g => g.length > 0);

    if (
        !selectedParseSessions ||
        Object.keys(selectedParseSessions).length === 0 ||
        (!parse_links && !hasSessionGroups) ||
        (is_parse_messages && !count_of_messages)
    ) {
        bridge.show_notification("Введите корректные данные");
        return;
    }

    const parse_data = {
        parse_links,
        count_of_posts,
        is_parse_messages,
        count_of_messages,
        selected_sessions: selectedParseSessions,
        session_groups,
    };
    document.getElementById("start-parsing-button").disabled = true;
    document.getElementById("parsing-status").innerText = "запуск...";
    await bridge.startParsing(JSON.stringify(parse_data));
}

async function stopParsing() {
    document.getElementById("stop-parsing-button").disabled = true;
    document.getElementById("parsing-status").innerText = "остановка...";
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
    const tagsEl = document.getElementById("active-parsing-tags");
    const tags = render_data.active_settings || [];
    if (tags.length > 0) {
        tagsEl.innerHTML = tags
            .map(t => `<span class="parsing-setting-tag">${t}</span>`)
            .join("");
        tagsEl.style.display = "flex";
    } else {
        tagsEl.style.display = "none";
        tagsEl.innerHTML = "";
    }
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
    const order = document.getElementById("mailing-order").value;

    if (is_parse_usernames && !mailing_data) {
        bridge.show_notification("Введите данные для рассылки");
        return;
    }

    const mail_data = {
        is_parse_usernames,
        is_send_text,
        mailing_data,
        delay,
        order,
        selected_sessions: selectedMailSessions,
    };

    document.getElementById("start-mailing-button").disabled = true;
    document.getElementById("mailing-status").innerText = "запуск...";
    await bridge.startMailing(JSON.stringify(mail_data));
}

async function stopMailing() {
    document.getElementById("stop-mailing-button").disabled = true;
    document.getElementById("mailing-status").innerText = "остановка...";
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

    const linksCheckbox = document.getElementById("send-links-to-parsed");
    const linksSelect   = document.getElementById("send-links-type");
    if (linksCheckbox && linksSelect) {
        linksSelect.disabled = !linksCheckbox.checked;
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
        else
            value = elem.value;
    } else if (elem_type === "select-one") {
        value = elem.value;
    }

    bridge.changeSettings(JSON.stringify({ key, value }));
    if (key === "pudge_default_group") {
        pudgeDefaultGroup = value || "";
        _updatePudgeGroupPlaceholders();
    }
}

function toggleLinksSelect(checkbox) {
    const select = document.getElementById("send-links-type");
    if (select) select.disabled = !checkbox.checked;
    changeSettings(checkbox);
}

async function refreshSessionManager() {
    await bridge.refreshSessionManager();
}

function resetSettings() {
    bridge.resetSettings();
}

const _actionButtonIds = { reset: "parsed-reset-btn", delete: "parsed-delete-btn" };
const _actionButtonTimers = {};

function parsedActionResult(action, success) {
    const btnId = _actionButtonIds[action];
    if (!btnId) return;
    const btn = document.getElementById(btnId);
    if (!btn) return;

    if (_actionButtonTimers[action]) {
        clearTimeout(_actionButtonTimers[action]);
        delete _actionButtonTimers[action];
    }

    btn.classList.remove("btn-action-success", "btn-action-error");
    btn.dataset.originalText = btn.dataset.originalText || btn.textContent;

    if (success) {
        btn.classList.add("btn-action-success");
        btn.textContent = "✓ Успешно";
    } else {
        btn.classList.add("btn-action-error");
        btn.textContent = "✗ Ошибка";
    }

    _actionButtonTimers[action] = setTimeout(() => {
        btn.classList.remove("btn-action-success", "btn-action-error");
        btn.textContent = btn.dataset.originalText;
        delete _actionButtonTimers[action];
    }, 4000);
}

let _confirmActionCallback = null;

function openConfirmActionModal(message, callback) {
    document.getElementById('confirm-action-message').textContent = message;
    document.getElementById('confirm-action-modal').classList.remove('hidden');
    _confirmActionCallback = callback;
}

function confirmAction() {
    const callback = _confirmActionCallback;
    closeConfirmActionModal();
    if (callback) callback();
}

function closeConfirmActionModal() {
    document.getElementById('confirm-action-modal').classList.add('hidden');
    _confirmActionCallback = null;
}

function resetParsedToSended() {
    bridge.isProcessActive(function(active) {
        if (active) {
            bridge.show_notification("Невозможно выполнить: активен парсинг или рассылка");
            return;
        }
        openConfirmActionModal(
            'Все неотправленные спаршенные пользователи будут отмечены как отправленные. Продолжить?',
            () => bridge.resetParsedToSended()
        );
    });
}

function deleteUnsendedParsed() {
    bridge.isProcessActive(function(active) {
        if (active) {
            bridge.show_notification("Невозможно выполнить: активен парсинг или рассылка");
            return;
        }
        openConfirmActionModal(
            'Все неотправленные спаршенные пользователи будут удалены из базы данных. Продолжить?',
            () => bridge.deleteUnsendedParsed()
        );
    });
}

// ═══════════════════════════════════════════════════════════════════
// PUDGE — default group helpers
// ═══════════════════════════════════════════════════════════════════

function setRenderPudgeDefaultGroup(group) {
    pudgeDefaultGroup = group || "";
    _updatePudgeGroupPlaceholders();
}

function _updatePudgeGroupPlaceholders() {
    const ph = pudgeDefaultGroup || "Ссылка на группу для уведомлений";
    document.querySelectorAll(".pudge-group-input").forEach(inp => { inp.placeholder = ph; });
}

// ═══════════════════════════════════════════════════════════════════
// PUDGE — session rendering
// ═══════════════════════════════════════════════════════════════════

function renderPudgeSessions(sessions_json) {
    const container = document.querySelector("#pudge-session-container-block .sessions-list");
    if (!container) return;

    const sessions = JSON.parse(sessions_json);

    const liveIds = new Set(sessions.map(s => String(s.session_id)));
    Object.keys(pudgeConfigs).forEach(sid => {
        if (!liveIds.has(sid)) {
            delete pudgeConfigs[sid];
            clearTimeout(_pudgeGroupInputTimers[sid]);
            delete _pudgeGroupInputTimers[sid];
        }
    });

    const fragment = document.createDocumentFragment();

    sessions.forEach((session) => {
        const sid = String(session.session_id);
        if (!pudgeConfigs[sid]) {
            pudgeConfigs[sid] = { send_to_saved: false, target_group: "", hook_ids: [] };
        }

        const cfg = pudgeConfigs[sid];
        const isRunning = session.pudgeRunning || false;
        const controlBtn = isRunning
            ? `<div class="btn stop-pudge" onclick="togglePudge(false, this)">Стоп</div>`
            : `<div class="btn start-pudge" onclick="togglePudge(true, this)">Начать</div>`;

        const row = document.createElement("div");
        row.className = "row";
        row.dataset.id = sid;
        row.dataset.file = session.session_file;

        row.innerHTML = `
            <div class="session-avatar-wrap">
                <div class="session-avatar-inner">${_buildSessionAvatar(session)}</div>
            </div>
            <div class="row-content">
                <div class="session-info">
                    Сессия: <span class="session-name">${session.session_file}</span>
                    Номер телефона: <span class="session-phone">${session.phone_number || "—"}</span>
                </div>
                <div class="pudge-config">
                    <label class="pudge-saved-label">
                        <input type="checkbox" class="pudge-send-saved" ${cfg.send_to_saved ? "checked" : ""}
                            onchange="toggleSendToSaved(this)">
                        отправлять в сохраненные сообщения
                    </label>
                </div>
                <div class="buttons">
                    <div class="pudge-group-row">
                        <input type="text" class="pudge-group-input"
                            placeholder="${pudgeDefaultGroup || 'Ссылка на группу для уведомлений'}"
                            value="${cfg.target_group || ""}"
                            ${cfg.send_to_saved ? "disabled" : ""}
                            oninput="onPudgeGroupInput(this)">
                        <div class="btn pudge-check-btn" onclick="checkPudgeAccess(this)">Проверить</div>
                    </div>
                    <div class="pudge-ctrl-btns">
                        <div class="btn open-groups" onclick="openHooksModal(this)">Хуки</div>
                        <div class="btn open-groups" onclick="openPudgeGroupsModal(this)">Группа</div>
                        <div class="btn open-groups" onclick="loadPudgeLinks(this)">Ссылки</div>
                        ${controlBtn}
                    </div>
                </div>
                <div class="pudge-check-status"></div>
                <div class="pudge-received">Получено: <span class="pudge-count">0</span></div>
            </div>
        `;
        if (isRunning) _setPudgeLocked(row, true);
        fragment.appendChild(row);
    });
    container.appendChild(fragment);
}

// ═══════════════════════════════════════════════════════════════════
// PUDGE — session card interactions
// ═══════════════════════════════════════════════════════════════════

function _getPudgeRow(elem) {
    return elem.closest(".row");
}

function _setPudgeLocked(row, locked) {
    const checkbox = row.querySelector(".pudge-send-saved");
    const groupInput = row.querySelector(".pudge-group-input");
    if (checkbox) checkbox.disabled = locked;
    if (groupInput) groupInput.disabled = locked || !!(checkbox && checkbox.checked);
    row.querySelectorAll(".pudge-ctrl-btns .open-groups").forEach(btn => {
        btn.classList.toggle("disabled", locked);
    });
}

function toggleSendToSaved(cb) {
    const row = _getPudgeRow(cb);
    if (!row) return;
    const sid = row.dataset.id;
    const input = row.querySelector(".pudge-group-input");
    const isChecked = cb.checked;
    input.disabled = isChecked;
    if (!pudgeConfigs[sid]) pudgeConfigs[sid] = { send_to_saved: false, target_group: "", hook_ids: [] };
    pudgeConfigs[sid].send_to_saved = isChecked;
    _syncPudgeConfig(sid);
}

function onPudgeGroupInput(input) {
    const row = _getPudgeRow(input);
    if (!row) return;
    const sid = row.dataset.id;
    if (!pudgeConfigs[sid]) pudgeConfigs[sid] = { send_to_saved: false, target_group: "", hook_ids: [] };
    pudgeConfigs[sid].target_group = input.value.trim();
    clearTimeout(_pudgeGroupInputTimers[sid]);
    _pudgeGroupInputTimers[sid] = setTimeout(() => _syncPudgeConfig(sid), 600);
}

async function _syncPudgeConfig(sid) {
    if (!pudgeConfigs[sid]) return;
    await bridge.updatePudgeConfig(sid, JSON.stringify(pudgeConfigs[sid]));
}

function _setPudgeCheckStatus(row, text, state) {
    const el = row.querySelector(".pudge-check-status");
    if (!el) return;
    clearTimeout(el._clearTimer);
    el.textContent = text;
    el.className = "pudge-check-status" + (state ? " pudge-check-status--" + state : "");
    el.style.display = "block";
    if (state && state !== "pending") {
        el._clearTimer = setTimeout(() => {
            el.style.display = "none";
            el.textContent = "";
            el.className = "pudge-check-status";
        }, 8000);
    }
}

async function checkPudgeAccess(btn) {
    const row = _getPudgeRow(btn);
    if (!row) return;
    const sid = row.dataset.id;
    const cfg = pudgeConfigs[sid] || {};
    if (cfg.send_to_saved) {
        _setPudgeCheckStatus(row, "Проверка не нужна: включена отправка в сохранённые сообщения", "neutral");
        return;
    }
    const group = row.querySelector(".pudge-group-input")?.value.trim() || pudgeDefaultGroup;
    if (!group) {
        _setPudgeCheckStatus(row, "Укажите группу для отправки уведомлений", "error");
        return;
    }
    if (btn.dataset.pending) return;
    const origHTML = btn.innerHTML;
    btn.innerHTML = '<div class="loader"></div>';
    btn.dataset.pending = "1";
    _setPudgeCheckStatus(row, "Проверка...", "pending");
    await bridge.checkPudgeAccess(sid, group);
    btn.innerHTML = origHTML;
    delete btn.dataset.pending;
}

function handlePudgeCheckResult(session_id, json_str) {
    const result = JSON.parse(json_str);
    const row = document.querySelector(`#pudge-session-container-block .row[data-id="${session_id}"]`);
    if (!row) return;
    if (result.ok) {
        _setPudgeCheckStatus(row, "✓ Группа проверена — отправка работает", "success");
    } else {
        _setPudgeCheckStatus(row, "✗ " + (result.error || "Неизвестная ошибка"), "error");
    }
}

async function togglePudge(is_start, btn) {
    const row = _getPudgeRow(btn);
    if (!row) return;
    const sid = row.dataset.id;
    if (btn.dataset.pending) return;
    btn.outerHTML = `<div class="btn pudge-loader" style="background-color: blue;"><div class="loader"></div></div>`;
    if (is_start) {
        await _syncPudgeConfig(sid);
        await bridge.startPudge(sid);
    } else {
        await bridge.stopPudge(sid);
    }
}

function changePudgeStatus(session_id, is_on) {
    const row = document.querySelector(`#pudge-session-container-block .row[data-id="${session_id}"]`);
    if (!row) return;
    const ctrl = row.querySelector(".pudge-ctrl-btns");
    if (!ctrl) return;
    _setPudgeLocked(row, is_on);
    ctrl.querySelector(".pudge-loader")?.remove();
    ctrl.querySelector(".start-pudge")?.remove();
    ctrl.querySelector(".stop-pudge")?.remove();
    if (is_on) {
        ctrl.insertAdjacentHTML("beforeend",
            `<div class="btn stop-pudge" onclick="togglePudge(false, this)">Стоп</div>`);
    } else {
        ctrl.insertAdjacentHTML("beforeend",
            `<div class="btn start-pudge" onclick="togglePudge(true, this)">Начать</div>`);
    }
}

function updatePudgeReceivedCount(session_id, count) {
    const row = document.querySelector(`#pudge-session-container-block .row[data-id="${session_id}"]`);
    if (!row) return;
    const span = row.querySelector(".pudge-count");
    if (span) span.textContent = String(count);
}

// ── Pudge groups modal (reuse existing links-modal) ────────────────

async function openPudgeGroupsModal(btn) {
    if (btn.classList.contains("disabled")) return;
    const row = _getPudgeRow(btn);
    if (!row) return;
    const session_id = row.dataset.id;
    const session_file = row.dataset.file || row.querySelector(".session-name")?.innerText || "";
    const modal = document.getElementById("links-modal");
    if (!modal) return;

    modal.dataset.id = session_id;
    modal.dataset.file = session_file;
    modal.dataset.context = "pudge";
    modal.dataset.fetchedIds = "[]";
    document.getElementById("links-list").innerHTML = "";
    document.getElementById("links-search").value = "";
    document.getElementById("links-select-all").checked = false;
    filterLinks("");
    const statusEl = document.getElementById("links-modal-status");
    if (statusEl) statusEl.textContent = "Загрузка...";
    _setLinksConfirmEnabled(false);
    modal.classList.remove("hidden");

    await bridge.loadPudgeSessionGroups(session_id, session_file);
}

function renderPudgeSessionGroups(session_id, groups_json) {
    const modal = document.getElementById("links-modal");
    if (!modal || modal.dataset.id !== String(session_id) || modal.dataset.context !== "pudge") return;

    const groups = JSON.parse(groups_json);
    const sessionFile = modal.dataset.file || "";
    modal.dataset.fetchedIds = JSON.stringify(groups.map(g => g.identifier));

    const list = document.getElementById("links-list");
    list.innerHTML = "";

    if (groups.length === 0) {
        list.innerHTML = '<div class="links-empty-msg">Нет групп или каналов</div>';
        _setLinksConfirmEnabled(false);
        const statusEl = document.getElementById("links-modal-status");
        if (statusEl) statusEl.textContent = "";
        return;
    }

    const fragment = document.createDocumentFragment();
    groups.forEach(g => {
        const item = document.createElement("div");
        item.className = "links-item" + (g.selected ? " selected" : "");
        item.onclick = () => toggleLinksItem(item);
        item.innerHTML = `
            <div class="links-item-photo">
                <div class="links-item-photo-inner">${_buildGroupPhoto(g, sessionFile)}</div>
                <div class="links-item-check">✓</div>
            </div>
            <div class="links-item-info">
                ${_buildEntityTypeIcon(g.entity_type)}
                <span class="links-item-name">${g.title}</span>
            </div>
            <input type="checkbox" value="${g.identifier}" ${g.selected ? "checked" : ""} hidden>
        `;
        fragment.appendChild(item);
    });
    list.appendChild(fragment);

    const allChecked = groups.every(g => g.selected);
    document.getElementById("links-select-all").checked = allChecked;
    const statusEl = document.getElementById("links-modal-status");
    if (statusEl) statusEl.textContent = "";
    _setLinksConfirmEnabled(true);
}

function pudgeGroupsStatus(session_id, status) {
    const modal = document.getElementById("links-modal");
    if (!modal || modal.dataset.id !== String(session_id) || modal.dataset.context !== "pudge") return;
    const statusEl = document.getElementById("links-modal-status");
    if (statusEl) statusEl.textContent = status;
}

// ── Pudge links modal ──────────────────────────────────────────────

async function loadPudgeLinks(btn) {
    if (btn.classList.contains("disabled")) return;
    const row = _getPudgeRow(btn);
    if (!row) return;
    await bridge.loadPudgeLinks(row.dataset.id);
}

function renderPudgeLinks(session_id, groups_data_str) {
    const modal = document.getElementById("pudge-links-modal");
    if (!modal) return;
    modal.dataset.id = session_id;
    modal.querySelector("textarea").value = groups_data_str;
    modal.classList.remove("hidden");
}

async function confirmPudgeLinks() {
    const modal = document.getElementById("pudge-links-modal");
    if (!modal) return closePudgeLinksModal();
    const groups_data = modal.querySelector("textarea").value;
    await bridge.updatePudgeLinks(modal.dataset.id, groups_data);
    closePudgeLinksModal();
}

function closePudgeLinksModal() {
    const modal = document.getElementById("pudge-links-modal");
    if (!modal) return;
    modal.dataset.id = "";
    modal.classList.add("hidden");
}

// ── Pudge hooks modal ──────────────────────────────────────────────

function openHooksModal(btn) {
    if (btn.classList.contains("disabled")) return;
    const row = _getPudgeRow(btn);
    if (!row) return;
    const sid = row.dataset.id;
    currentPudgeHooksSessionId = sid;

    const cfg = pudgeConfigs[sid] || { hook_ids: [] };
    const selectedIds = new Set(cfg.hook_ids.map(Number));
    const list = document.getElementById("pudge-hooks-list");
    const footer = document.querySelector("#pudge-hooks-modal .links-modal-footer");
    list.innerHTML = "";

    const selectAllRow = document.getElementById("hooks-select-all-row");
    const selectAllCb = document.getElementById("hooks-select-all");

    if (allHookMessages.length === 0) {
        list.innerHTML = '<div class="links-empty-msg">Нет сообщений для хуков.<br>Добавьте их во вкладке «Сообщения → Для хуков».</div>';
        if (selectAllRow) selectAllRow.style.display = "none";
        if (footer) footer.innerHTML = `
            <div class="button accept-btn" onclick="closePudgeHooksModal()">Понятно</div>
        `;
    } else {
        if (selectAllRow) selectAllRow.style.display = "";
        allHookMessages.forEach(msg => {
            const item = document.createElement("label");
            item.className = "hooks-modal-item";
            item.innerHTML = `
                <input type="checkbox" value="${msg.id}" ${selectedIds.has(msg.id) ? "checked" : ""}
                    onchange="_updateHooksSelectAll()">
                <span>${_escapeHtml(msg.text)}</span>
            `;
            list.appendChild(item);
        });
        if (footer) footer.innerHTML = `
            <div class="button accept-btn" onclick="confirmHooksSelection()">Подтвердить</div>
            <div class="button cancel-btn" onclick="closePudgeHooksModal()">Отмена</div>
        `;
        // Sync select-all state with current selection
        if (selectAllCb) {
            const allChecked = allHookMessages.every(m => selectedIds.has(m.id));
            selectAllCb.checked = allChecked;
        }
    }

    document.getElementById("pudge-hooks-modal").classList.remove("hidden");
}

async function confirmHooksSelection() {
    const sid = currentPudgeHooksSessionId;
    if (!sid) return closePudgeHooksModal();

    const checked = [...document.querySelectorAll("#pudge-hooks-list input[type='checkbox']:checked")]
        .map(cb => Number(cb.value));

    if (!pudgeConfigs[sid]) pudgeConfigs[sid] = { send_to_saved: false, target_group: "", hook_ids: [] };
    pudgeConfigs[sid].hook_ids = checked;
    await _syncPudgeConfig(sid);
    closePudgeHooksModal();
}

function toggleAllHooks(checkbox) {
    document.querySelectorAll("#pudge-hooks-list input[type='checkbox']").forEach(cb => {
        cb.checked = checkbox.checked;
    });
}

function _updateHooksSelectAll() {
    const cbs = [...document.querySelectorAll("#pudge-hooks-list input[type='checkbox']")];
    const selectAll = document.getElementById("hooks-select-all");
    if (selectAll && cbs.length > 0) {
        selectAll.checked = cbs.every(cb => cb.checked);
    }
}

function closePudgeHooksModal() {
    document.getElementById("pudge-hooks-modal").classList.add("hidden");
    currentPudgeHooksSessionId = null;
}

// ═══════════════════════════════════════════════════════════════════
// HOOK MESSAGES — management in SMM → Для хуков tab
// ═══════════════════════════════════════════════════════════════════

function renderHookMessages(json_str) {
    allHookMessages = JSON.parse(json_str);

    const list = document.getElementById("hook-message-list");
    if (!list) return;
    list.innerHTML = "";

    const fragment = document.createDocumentFragment();
    allHookMessages.forEach((msg, index) => {
        const row = document.createElement("div");
        row.className = "row";
        row.dataset.id = msg.id;
        row.innerHTML = `
            <div class="row-content">
                <div class="left-smm-side">
                    <div class="index">${index + 1}.</div>
                    <input type="text" class="hook-msg-text" value="${_escapeHtml(msg.text)}" disabled>
                </div>
                <div class="buttons">
                    <div class="btn edit-btn">
                        <img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editHookMessage(this)">
                    </div>
                    <div class="btn delete-btn">
                        <img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteHookMessage(this)">
                    </div>
                </div>
            </div>
        `;
        fragment.appendChild(row);
    });
    list.appendChild(fragment);
}

function _escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

async function addHookMessage() {
    const input = document.getElementById("newHookMessage");
    if (!input || !input.value.trim()) return;
    await bridge.addHookMessage(input.value.trim());
    input.value = "";
}

async function deleteHookMessage(btn) {
    const row = btn.closest(".row");
    if (!row) return;
    await bridge.deleteHookMessage(String(row.dataset.id));
}

function editHookMessage(btn) {
    const row = btn.closest(".row");
    if (!row) return;
    const input = row.querySelector(".hook-msg-text");
    const buttons = row.querySelector(".buttons");
    input.dataset.original = input.value;
    input.disabled = false;
    input.focus();
    buttons.innerHTML = `
        <div class="btn accept-btn">
            <img class="icons" src="assets/icons/mark.png" alt="save" onclick="saveHookMessageChanges(this)">
        </div>
        <div class="btn cancel-btn">
            <img class="icons" src="assets/icons/cancel.png" alt="cancel" onclick="cancelHookMessageEdit(this)">
        </div>
    `;
}

async function saveHookMessageChanges(btn) {
    const row = btn.closest(".row");
    if (!row) return;
    const input = row.querySelector(".hook-msg-text");
    const newText = input.value.trim();
    if (!newText) { cancelHookMessageEdit(btn); return; }
    await bridge.saveHookMessageChanges(JSON.stringify({ id: row.dataset.id, text: newText }));
}

function cancelHookMessageEdit(btn) {
    const row = btn.closest(".row");
    if (!row) return;
    const input = row.querySelector(".hook-msg-text");
    const buttons = row.querySelector(".buttons");
    input.value = input.dataset.original || input.value;
    input.disabled = true;
    buttons.innerHTML = `
        <div class="btn edit-btn">
            <img class="icons" src="assets/icons/edit.png" alt="edit" onclick="editHookMessage(this)">
        </div>
        <div class="btn delete-btn">
            <img class="icons" src="assets/icons/delete.png" alt="delete" onclick="deleteHookMessage(this)">
        </div>
    `;
}
