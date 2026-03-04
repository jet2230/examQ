(function() {
    const username = localStorage.getItem('quiz_username') || localStorage.getItem('quiz_admin_username');
    if (!username) return;

    let activeChatUser = null;
    let pollInterval = null;
    let lastUnreadCount = 0;
    let unreadBySender = {};

    // --- Create and Inject UI ---
    function injectUI() {
        const navbar = document.querySelector('.navbar');
        const brand = document.querySelector('.nav-brand') || navbar?.querySelector('div:first-child');
        if (!navbar || !brand) return;

        // Container for online status
        const statusContainer = document.createElement('div');
        statusContainer.id = 'onlineStatusContainer';
        statusContainer.style.cssText = `
            display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 5px 12px;
            border-radius: 20px; background: rgba(40, 167, 69, 0.1); transition: all 0.2s;
            position: relative; margin-left: 15px; white-space: nowrap; z-index: 1001;
        `;
        statusContainer.onclick = toggleOnlineList;

        statusContainer.innerHTML = `
            <div style="width: 10px; height: 10px; background: #28a745; border-radius: 50%; box-shadow: 0 0 5px #28a745;"></div>
            <span id="onlineCount" style="font-weight: 700; color: #28a745; font-size: 0.85em;">Online: 1</span>
            <span id="totalUnreadBadge" style="display:none; background:#dc3545; color:white; font-size:0.75em; padding:2px 7px; border-radius:10px; margin-left:8px; font-weight: 800; border: 1px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.2); animation: pulse 2s infinite;">0</span>
        `;

        // Add pulse animation
        if (!document.getElementById('pulseAnimation')) {
            const style = document.createElement('style');
            style.id = 'pulseAnimation';
            style.textContent = `
                @keyframes pulse { 0% { transform: scale(1); } 50% { transform: scale(1.1); } 100% { transform: scale(1); } }
            `;
            document.head.appendChild(style);
        }

        // Online Users List (Popup)
        const userList = document.createElement('div');
        userList.id = 'onlineUserList';
        userList.style.cssText = `
            position: absolute; top: 100%; left: 0; width: 220px; background: white;
            border: 1px solid #eee; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            padding: 15px; display: none; z-index: 2000; margin-top: 10px;
        `;
        userList.innerHTML = `<h4 style="margin-bottom: 10px; color: #666; font-size: 0.9em; border-bottom: 1px solid #eee; padding-bottom: 5px;">Active Users</h4><div id="usersContainer"></div>`;
        
        // Chat Window (Global)
        const chatWin = document.createElement('div');
        chatWin.id = 'chatWindow';
        chatWin.style.cssText = `
            position: fixed; bottom: 20px; right: 20px; width: 300px; height: 400px;
            background: white; border-radius: 15px 15px 0 0; box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            display: none; flex-direction: column; z-index: 3000; overflow: hidden; border: 1px solid #ddd;
        `;
        chatWin.innerHTML = `
            <div style="background: #1e3c72; color: white; padding: 12px 15px; display: flex; justify-content: space-between; align-items: center;">
                <strong id="chatTitle">Chat</strong>
                <span style="cursor:pointer; font-size: 20px;" onclick="closeChat()">&times;</span>
            </div>
            <div id="chatMessages" style="flex: 1; padding: 15px; overflow-y: auto; background: #f9f9f9; display: flex; flex-direction: column; gap: 10px;"></div>
            <div style="padding: 10px; border-top: 1px solid #eee; display: flex; gap: 5px;">
                <input type="text" id="chatInput" placeholder="Type a message..." style="flex: 1; padding: 8px; border: 1px solid #ddd; border-radius: 5px; outline: none;">
                <button onclick="sendMessage()" style="background: #1e3c72; color: white; border: none; padding: 5px 12px; border-radius: 5px; cursor: pointer;">Send</button>
            </div>
        `;

        document.body.appendChild(chatWin);
        statusContainer.appendChild(userList);
        brand.after(statusContainer);

        document.getElementById('chatInput').onkeydown = (e) => { if (e.key === 'Enter') sendMessage(); };
    }

    function toggleOnlineList(e) {
        e.stopPropagation();
        const list = document.getElementById('onlineUserList');
        const isVisible = list.style.display === 'block';
        if (!isVisible) {
            list.style.display = 'block';
            updateOnlineUsers();
        } else {
            list.style.display = 'none';
        }
    }

    window.openChat = function(targetUser) {
        if (targetUser === username) return;
        activeChatUser = targetUser;
        const displayUser = targetUser.length > 10 ? targetUser.substring(0, 10) + '...' : targetUser;
        document.getElementById('chatTitle').textContent = 'Chat with ' + displayUser;
        document.getElementById('chatTitle').title = targetUser; // Full name on hover
        document.getElementById('chatWindow').style.display = 'flex';
        const msgContainer = document.getElementById('chatMessages');
        msgContainer.innerHTML = '';
        msgContainer.removeAttribute('data-msg-count'); // Reset count for new user
        fetchMessages();
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(fetchMessages, 3000);
    };

    window.closeChat = function() {
        document.getElementById('chatWindow').style.display = 'none';
        activeChatUser = null;
        if (pollInterval) clearInterval(pollInterval);
    };

    function linkify(text) {
        const urlRegex = /(https?:\/\/[^\s]+)/g;
        return text.replace(urlRegex, function(url) {
            return `<a href="${url}" target="_blank" style="color: inherit; text-decoration: underline;">${url}</a>`;
        });
    }

    async function fetchMessages() {
        if (!activeChatUser) return;
        try {
            const res = await fetch(`/api/messages/get?username=${username}&other=${activeChatUser}`);
            const data = await res.json();
            if (data.success) {
                const container = document.getElementById('chatMessages');
                const msgCount = data.messages.length;
                
                // Use a data attribute to check if we actually need to re-render
                if (container.getAttribute('data-msg-count') !== msgCount.toString()) {
                    const html = data.messages.map(m => {
                        const isMe = m.sender === username;
                        return `
                            <div style="align-self: ${isMe ? 'flex-end' : 'flex-start'}; background: ${isMe ? '#1e3c72' : '#e9e9e9'}; color: ${isMe ? 'white' : 'black'}; padding: 8px 12px; border-radius: 12px; max-width: 80%; font-size: 0.9em; box-shadow: 0 2px 5px rgba(0,0,0,0.05); overflow-wrap: anywhere; word-break: break-word;">
                                ${linkify(m.message)}
                            </div>
                        `;
                    }).join('');
                    
                    container.innerHTML = html;
                    container.setAttribute('data-msg-count', msgCount);
                    container.scrollTop = container.scrollHeight;
                }

                // If we received new messages from the other user, mark them as read
                if (data.messages.some(m => m.sender === activeChatUser && m.is_read === 0)) {
                    await fetch('/api/messages/read', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ username, other: activeChatUser })
                    });
                    checkUnread(); // Update the badge
                }
            }
        } catch (e) {}
    }

    window.sendMessage = async function() {
        const input = document.getElementById('chatInput');
        const msg = input.value.trim();
        if (!msg || !activeChatUser) return;

        try {
            const res = await fetch('/api/messages/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sender: username, recipient: activeChatUser, message: msg })
            });
            if ((await res.json()).success) {
                input.value = '';
                fetchMessages();
            }
        } catch (e) {}
    };

    function formatRelativeTime(isoStr) {
        if (!isoStr) return 'Never';
        const date = new Date(isoStr.replace(' ', 'T') + (isoStr.includes('Z') ? '' : 'Z'));
        const diffMs = new Date() - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        return `${diffDays}d ago`;
    }

    async function updateOnlineUsers() {
        try {
            const res = await fetch('/api/users/all');
            const data = await res.json();
            if (data.success) {
                const onlineCount = data.users.filter(u => u.is_online).length;
                document.getElementById('onlineCount').textContent = `Online: ${onlineCount}`;
                const container = document.getElementById('usersContainer');
                if (container) {
                    container.innerHTML = data.users.map(u => {
                        const displayUser = u.username.length > 10 ? u.username.substring(0, 10) + '...' : u.username;
                        const unreadCount = unreadBySender[u.username] || 0;
                        const unreadBadge = unreadCount > 0 ? `<span style="background:#dc3545; color:white; font-size:0.7em; padding:1px 5px; border-radius:10px; margin-left:5px;">${unreadCount}</span>` : '';
                        
                        return `
                            <div onclick="openChat('${u.username}')" style="display: flex; flex-direction: column; gap: 2px; margin-bottom: 10px; cursor: pointer; padding: 5px; border-radius: 5px; transition: background 0.2s; min-width: 0;" onmouseover="this.style.background='#f0f4f9'" onmouseout="this.style.background='transparent'">
                                <div style="display: flex; align-items: center; gap: 8px; width: 100%;">
                                    <div style="width: 8px; height: 8px; background: ${u.is_online ? '#28a745' : '#ccc'}; border-radius: 50%; ${u.is_online ? 'box-shadow: 0 0 3px #28a745;' : ''} flex-shrink: 0;"></div>
                                    <strong style="flex:1; color: ${u.is_online ? '#333' : '#666'}; font-size: 0.95em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${u.username}">${displayUser}</strong>
                                    ${unreadBadge}
                                    ${u.role === 'admin' ? '<span style="font-size: 0.65em; background: #d63384; color: white; padding: 1px 5px; border-radius: 4px; flex-shrink: 0;">ADMIN</span>' : ''}
                                </div>
                                <div style="font-size: 0.75em; color: #999; margin-left: 16px;">
                                    ${u.is_online ? 'Online now' : 'Last active: ' + formatRelativeTime(u.last_online)}
                                </div>
                            </div>
                        `;
                    }).join('');
                }
            }
        } catch (e) {}
    }

    async function checkUnread() {
        try {
            const res = await fetch(`/api/messages/unread-count?username=${username}`);
            const data = await res.json();
            const badge = document.getElementById('totalUnreadBadge');
            if (!badge) return;

            unreadBySender = data.by_sender || {};

            if (data.count > lastUnreadCount) {
                showNotification(`You have ${data.count} unread message(s)`);
            }
            
            lastUnreadCount = data.count;

            if (data.count > 0) {
                badge.textContent = data.count;
                badge.style.display = 'inline-block';
                updateOnlineUsers(); 
            } else {
                badge.style.display = 'none';
            }
        } catch (e) {}
    }

    function showNotification(msg) {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; top: 80px; right: 20px; background: #1e3c72; color: white;
            padding: 12px 25px; border-radius: 8px; box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            z-index: 9999; font-weight: 600; font-size: 0.9em; animation: slideIn 0.3s ease;
        `;
        toast.innerHTML = `💬 ${msg}`;
        document.body.appendChild(toast);

        if (!document.getElementById('toastAnimation')) {
            const style = document.createElement('style');
            style.id = 'toastAnimation';
            style.textContent = `
                @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
                @keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
            `;
            document.head.appendChild(style);
        }

        setTimeout(() => {
            toast.style.animation = 'fadeOut 0.5s ease forwards';
            setTimeout(() => toast.remove(), 500);
        }, 4000);
    }

    async function sendHeartbeat() {
        try {
            await fetch('/api/user/heartbeat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ username })
            });
            updateOnlineUsers();
            checkUnread();
        } catch (e) {}
    }

    // Initialize
    window.addEventListener('load', () => {
        injectUI();
        sendHeartbeat();
        checkUnread();
        setInterval(sendHeartbeat, 30000);
        setInterval(checkUnread, 5000);
    });

    window.addEventListener('click', (e) => {
        const list = document.getElementById('onlineUserList');
        if (list && !document.getElementById('onlineStatusContainer').contains(e.target)) {
            list.style.display = 'none';
        }
    });
})();
