let bridge = null;

new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.chatBridge;

    bridge.renderMessages.connect(renderMessages);
    bridge.clearChatWindow.connect(clearChatWindow);
});

function changeSize(elem) {
    elem.style.height = "auto";
    elem.style.height = elem.scrollHeight + "px";
}

document.getElementById("input-field").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

function renderMessages(messages_raw, user_id, session, is_old, user_data_str) {
    let chat_window_div = document.getElementById("chat-window");
    if (!chat_window_div) return;

    if (user_data_str !== "{}") {
        const user_data = JSON.parse(user_data_str);
        document.getElementById("profile-image").innerHTML =
            user_data.profile_photo;
        document.getElementById("full-name").innerText = user_data.user_full_name;
        document.getElementById("username").innerText = user_data.username
            ? `@${user_data.username}`
            : "";
        document.getElementById("user-id").innerText = `id: ${user_id}`;
    }

    const messages = JSON.parse(messages_raw);
    const chat_messages = document.getElementById("chat-history");
    if (is_old === 0) chat_messages.innerHTML = "";

    messages.forEach((message) => {
        const message_div = document.createElement("div");
        message_div.className = "message";
        message_div.classList.add(message.is_out ? "my" : "sender");
        message_div.dataset.id = message.message_id;

        let attachment_html = "";
        let mime_types = JSON.parse(message.attachment_type || "[]");
        const attachments = JSON.parse(message.attachment || "[]");

        if (mime_types[0] === "album") {
            mime_types.shift();
            attachment_html = '<div class="album">';
            for (let i = 0; i < mime_types.length; i++)
                attachment_html += renderAttachment(
                    mime_types[i],
                    attachments[i],
                    `${user_id}_${session}`,
                );
            attachment_html += "</div>";
        } else if (attachments.length === 1 && mime_types.length === 1)
            attachment_html = renderAttachment(
                mime_types[0],
                attachments[0],
                `${user_id}_${session}`,
            );

        message_div.innerHTML = `${attachment_html}
            <div class="text">${message.text}</div>
            <div class="time">${message.created_at}</div>
        `;
        chat_messages.appendChild(message_div);
    });
}

function renderAttachment(mime_type, attachment, user_session) {
    const path = `../assets/users_data/${user_session}/${attachment}`;

    if (mime_type.startsWith("image/"))
        return `<img src="${path}" alt='${attachment}'>`;
    else if (mime_type.startsWith("audio/")) {
        if (mime_type.endsWith("ogg") || mime_type.endsWith("oga"))
            return `Голосовое сообщение: <audio src="${path}" controls></audio>`;
        else
            return `Аудио файл: ${attachment} <audio src="${path}" controls></audio>`;
    } else if (mime_type.startsWith("video/"))
        return `<div class="video-placeholder" onclick="openVideoPlayer('${path}')">▶ Видео</div>`;
    else if (mime_type === "application/pdf")
        return `<div>PDF: <a href="${path}" target="_blank">${attachment}</a></div>`;
    else if (mime_type === "contact") {
        const attachment_raw = JSON.parse(attachment);
        return `<div>Contact: ${attachment_raw.phone_number}, ${attachment_raw.first_name || ""} ${attachment_raw.last_name || ""}. User_id: ${attachment_raw.user_id || ""}</div>`;
    } else return `<div>Файл: <a href="${path}" download>${attachment}</a></div>`;
}

function openVideoPlayer(path) {
    bridge.openVideoPlayer(path);
}

function attachMedia(elem) {
    const file_preview = document.getElementById("file-name");
    const file = elem.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64data = e.target.result.split(",")[1];
            file_preview.dataset.base64 = base64data;
            file_preview.textContent = file.name;
            elem.value = "";
        };
        reader.readAsDataURL(file);
    }
    document.getElementById("attached-file").style.display = "flex";
}

function removeFile() {
    const file_preview = document.getElementById("file-name");
    if (!file_preview.dataset.base64) return;

    delete file_preview.dataset.base64;
    file_preview.textContent = "";
    document.getElementById("attached-file").style.display = "none";
}

async function sendMessage() {
    const input_field = document.getElementById("input-field");
    const input_text = input_field.value.trim();
    const file_preview = document.getElementById("file-name");

    if (input_text === "" && !file_preview.dataset.base64) return;

    const send_message = {
        text: input_text !== "" ? input_text : null,
        filename: file_preview.textContent.trim(),
        base64_file: file_preview.dataset.base64,
    };
    await bridge.sendMessage(JSON.stringify(send_message));
    input_field.value = "";
    document.getElementById("remove-file").click();
}

function clearChatWindow() {
    document.getElementById("chat-history").innerHTML = "";
}

