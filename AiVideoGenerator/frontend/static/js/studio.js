(() => {
    "use strict";
    const $ = (id) => document.getElementById(id);
    const form = $("generation-form");
    const prompt = $("prompt");
    const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
    const maxBytes = Number($("app").dataset.maxImageMb) * 1024 * 1024;
    let conversationId = null;
    let imageFile = null;
    let previewUrl = null;
    let requestId = null;
    let sending = false;
    let pollTimer = null;
    let viewVersion = 0;
    const cards = new Map();

    function error(message = "") {
        $("error-banner").textContent = message;
        $("error-banner").hidden = !message;
    }

    async function api(url, options = {}) {
        let response;
        try {
            response = await fetch(url, {
                ...options, credentials: "same-origin",
                headers: { "X-CSRFToken": csrf, ...options.headers },
            });
        } catch {
            throw new Error("Connection lost. Check your connection and try again.");
        }
        if (response.status === 401) {
            location.assign("/auth/login/");
            throw new Error("Please log in again.");
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "The request could not be completed. Please try again.");
        }
        return data;
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function selectImage(file) {
        if (!file) return;
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
            error("Choose a PNG, JPEG or WebP image.");
            return;
        }
        if (file.size > maxBytes) {
            error(`Choose an image smaller than ${maxBytes / 1048576} MB.`);
            return;
        }
        if (sending) return;
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        imageFile = file;
        previewUrl = URL.createObjectURL(file);
        $("attachment-preview").src = previewUrl;
        $("attachment-name").textContent = file.name || "Pasted image.png";
        $("attachment").hidden = false;
        error();
        prompt.focus();
    }

    function removeImage() {
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = null;
        imageFile = null;
        $("attachment").hidden = true;
        $("attachment-preview").removeAttribute("src");
        $("image-input").value = "";
    }

    function updateCount() {
        $("character-count").textContent = `${prompt.value.length.toLocaleString()} / 2,000`;
    }

    async function refreshConversations() {
        const data = await api("/api/conversations/");
        const list = $("conversations");
        list.replaceChildren();
        $("creation-count").textContent = data.conversations.length;
        if (!data.conversations.length) {
            list.append(element("p", "empty-history", "Your ideas will find a home here."));
        }
        data.conversations.forEach((item) => {
            const button = element("button", "conversation-link");
            button.type = "button";
            button.title = item.title;
            button.classList.toggle("active", item.id === conversationId);
            button.append(element("span", "conversation-icon", "▱"), element("span", "", item.title));
            button.addEventListener("click", () => openConversation(item.id));
            list.append(button);
        });
    }

    function renderJob(job) {
        let card = cards.get(job.id);
        if (!card) {
            card = element("article", "generation-card");
            card.append(element("div", "message-author", "YOU"));
            const image = element("img", "message-image");
            image.src = job.image_url;
            image.alt = job.image_name;
            image.loading = "lazy";
            card.append(image, element("p", "message-prompt", job.prompt));
            const reply = element("div", "generation-reply");
            reply.append(element("span", "reply-mark", "✳"));
            const content = element("div", "reply-content");
            content.append(element("span", "reply-heading", "AiVideoGenerator"));
            content.append(element("div", "job-state"), element("div", "job-result"));
            reply.append(content);
            card.append(reply);
            cards.set(job.id, card);
            $("messages").append(card);
        }
        const signature = `${job.status}:${job.message}:${job.video_url}`;
        if (card.dataset.state === signature) return;
        card.dataset.state = signature;
        const state = card.querySelector(".job-state");
        state.replaceChildren();
        state.append(element("span", `status status-${job.status}`, job.label));
        state.append(element("p", "job-message", job.message));
        if (job.status === "queued") {
            state.append(element("small", "muted", "Your video will start when the renderer is available."));
        }
        const result = card.querySelector(".job-result");
        if (job.status === "completed" && job.video_url && !result.firstChild) {
            const video = element("video", "result-video");
            video.controls = true;
            video.playsInline = true;
            video.preload = "metadata";
            video.src = job.video_url;
            const download = element("a", "download-link", "Download video ↓");
            download.href = `${job.video_url}?download=1`;
            result.append(video, download);
        }
        $("announcer").textContent = `Video ${job.label.toLowerCase()}. ${job.message}`;
    }

    async function poll(id, version) {
        clearTimeout(pollTimer);
        try {
            const data = await api(`/api/conversations/${id}/`);
            if (version !== viewVersion || id !== conversationId) return;
            $("welcome").hidden = data.generations.length > 0;
            $("messages").hidden = !data.generations.length;
            data.generations.forEach(renderJob);
            if (data.generations.some((job) => ['queued', 'submitting', 'running'].includes(job.status))) {
                pollTimer = setTimeout(() => poll(id, version), 3000);
            }
        } catch (exception) {
            if (version !== viewVersion) return;
            error(exception.message);
            pollTimer = setTimeout(() => poll(id, version), 6000);
        }
    }

    async function openConversation(id) {
        if (sending) return;
        viewVersion += 1;
        conversationId = id;
        requestId = null;
        cards.clear();
        $("messages").replaceChildren();
        error();
        $("sidebar").classList.remove("open");
        $("menu-toggle").setAttribute("aria-expanded", "false");
        await Promise.all([poll(id, viewVersion), refreshConversations()]).catch((e) => error(e.message));
    }

    function newChat() {
        if (sending) return;
        clearTimeout(pollTimer);
        viewVersion += 1;
        conversationId = null;
        requestId = null;
        cards.clear();
        $("messages").replaceChildren();
        $("messages").hidden = true;
        $("welcome").hidden = false;
        prompt.value = "";
        updateCount();
        removeImage();
        error();
        $("sidebar").classList.remove("open");
        $("menu-toggle").setAttribute("aria-expanded", "false");
        refreshConversations().catch((e) => error(e.message));
        prompt.focus();
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (sending) return;
        if (!imageFile) return error("Add or paste a starting image first.");
        if (!prompt.value.trim()) return error("Describe what you want to happen in the video.");
        sending = true;
        error();
        $("generate-button").disabled = true;
        $("generate-button").textContent = "Sending…";
        prompt.readOnly = true;
        $("remove-image").disabled = true;
        try {
            if (!conversationId) {
                const conversation = await api("/api/conversations/new/", { method: "POST" });
                conversationId = conversation.id;
            }
            requestId ||= crypto.randomUUID();
            const body = new FormData();
            body.append("request_id", requestId);
            body.append("prompt", prompt.value.trim());
            body.append("image", imageFile, imageFile.name || "pasted-image.png");
            const job = await api(`/api/conversations/${conversationId}/generate/`, { method: "POST", body });
            requestId = null;
            $("welcome").hidden = true;
            $("messages").hidden = false;
            renderJob(job);
            prompt.value = "";
            updateCount();
            removeImage();
            $("workspace-scroll").scrollTop = $("workspace-scroll").scrollHeight;
            await refreshConversations();
            poll(conversationId, viewVersion);
        } catch (exception) {
            error(exception.message);
        } finally {
            sending = false;
            prompt.readOnly = false;
            $("remove-image").disabled = false;
            $("generate-button").disabled = false;
            $("generate-button").textContent = "Generate ↑";
        }
    });

    $("attach-button").addEventListener("click", () => $("image-input").click());
    $("image-input").addEventListener("change", (event) => selectImage(event.target.files[0]));
    $("remove-image").addEventListener("click", removeImage);
    $("new-chat").addEventListener("click", newChat);
    prompt.addEventListener("input", updateCount);
    prompt.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
    document.addEventListener("paste", (event) => {
        const item = Array.from(event.clipboardData?.items || []).find((entry) => entry.type.startsWith("image/"));
        if (item) { event.preventDefault(); selectImage(item.getAsFile()); }
    });
    document.addEventListener("dragover", (event) => {
        if (Array.from(event.dataTransfer.types).includes("Files")) event.preventDefault();
    });
    document.addEventListener("drop", (event) => {
        if (event.dataTransfer.files.length) {
            event.preventDefault();
            form.classList.remove("dragging");
            selectImage(event.dataTransfer.files[0]);
        }
    });
    form.addEventListener("dragenter", () => form.classList.add("dragging"));
    form.addEventListener("dragleave", (event) => {
        if (!form.contains(event.relatedTarget)) form.classList.remove("dragging");
    });
    document.querySelectorAll(".suggestion").forEach((button) => button.addEventListener("click", () => {
        if (sending) return;
        prompt.value = button.dataset.prompt;
        updateCount();
        prompt.focus();
    }));
    $("menu-toggle").addEventListener("click", () => {
        const open = $("sidebar").classList.toggle("open");
        $("menu-toggle").setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("keydown", (event) => {
        if (event.key.toLowerCase() === "n" && !event.ctrlKey && !event.metaKey
            && !['INPUT', 'TEXTAREA', 'BUTTON'].includes(document.activeElement.tagName)) newChat();
        if (event.key === "Escape") {
            $("sidebar").classList.remove("open");
            $("menu-toggle").setAttribute("aria-expanded", "false");
        }
    });
    refreshConversations().catch((exception) => error(exception.message));
})();
