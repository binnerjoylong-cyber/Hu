document.addEventListener('DOMContentLoaded', () => {
    
    // --- Element References ---
    const urlInput = document.getElementById('bot-url-input');
    const saveButton = document.getElementById('save-url-button');
    const recheckButton = document.getElementById('recheck-button');
    const statusIndicator = document.getElementById('bot-status-indicator');
    const statusText = document.getElementById('bot-status-text');
    const lastCheckedText = document.getElementById('last-checked');

    const STORAGE_KEY = 'lailaBotServiceURL';

    // --- Function to update status display ---
    function setStatus(status, message) {
        statusIndicator.className = 'status-dot'; // Reset classes
        switch (status) {
            case 'online':
                statusIndicator.classList.add('online');
                statusText.textContent = `Online: Server is responding.`;
                recheckButton.disabled = false;
                break;
            case 'offline':
                statusIndicator.classList.add('offline');
                statusText.textContent = `Offline: Server is not responding.`;
                recheckButton.disabled = false;
                break;
            case 'pending':
            default:
                statusIndicator.classList.add('pending');
                statusText.textContent = message || 'Checking status...';
                recheckButton.disabled = true;
                break;
        }
    }

    // --- Core Function: Check Bot Status ---
    async function checkBotStatus() {
        const botUrl = urlInput.value;
        if (!botUrl || !botUrl.startsWith('https:')) {
            setStatus('offline', 'Please enter a valid https:// URL.');
            return;
        }

        setStatus('pending');
        lastCheckedText.textContent = 'Checking...';
        
        const startTime = Date.now();
        
        try {
            // We ping the bot's Web Service URL.
            // 'no-cors' mode is crucial. It allows the request even if the
            // server doesn't send CORS headers. We can't read the response,
            // but we know if the server is reachable if it doesn't throw an error.
            await fetch(botUrl, { mode: 'no-cors' });
            
            // If fetch succeeds (doesn't throw), the server is reachable.
            const responseTime = Date.now() - startTime;
            setStatus('online');
            lastCheckedText.textContent = `Last checked: ${new Date().toLocaleTimeString()} (Response: ${responseTime}ms)`;

        } catch (error) {
            // If fetch throws an error (e.g., TypeError: Failed to fetch),
            // it means the server is down or unreachable.
            setStatus('offline');
            lastCheckedText.textContent = `Last checked: ${new Date().toLocaleTimeString()}`;
        }
    }

    // --- Event Listeners ---
    saveButton.addEventListener('click', () => {
        const botUrl = urlInput.value;
        if (botUrl && botUrl.startsWith('https://')) {
            localStorage.setItem(STORAGE_KEY, botUrl);
            alert('URL Saved! Checking status...');
            checkBotStatus();
        } else {
            alert('Please enter a valid https:// URL (e.g., https://your-bot.onrender.com)');
        }
    });

    recheckButton.addEventListener('click', checkBotStatus);

    // --- On Page Load ---
    function initialize() {
        const savedUrl = localStorage.getItem(STORAGE_KEY);
        if (savedUrl) {
            urlInput.value = savedUrl;
            checkBotStatus();
        } else {
            setStatus('offline', 'Please save your Bot Web Service URL to begin.');
            lastCheckedText.textContent = 'Ready to check.';
        }
    }

    initialize();
});
