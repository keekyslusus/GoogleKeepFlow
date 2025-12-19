async function solveChallenge(challenge, difficulty) {
    const target = '0'.repeat(difficulty);
    let nonce = 0;
    while (true) {
        const data = challenge + nonce.toString();
        const hashHex = sha256(data);
        if (hashHex.startsWith(target)) {
            return nonce.toString();
        }
        nonce++;
        if (nonce % 10000 === 0) {
            await new Promise(r => setTimeout(r, 0));
        }
    }
}

function copyToken() {
    const tokenBox = document.getElementById('tokenBox');
    if (!tokenBox) {
        console.error('Token box not found');
        return;
    }
    
    const token = tokenBox.textContent;
    const btn = document.querySelector('.copy-btn');
    
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(token)
            .then(() => showCopySuccess(btn))
            .catch(err => {
                console.warn('Clipboard API failed:', err);
                fallbackCopy(token, btn);
            });
    } else {
        fallbackCopy(token, btn);
    }
}

function selectTokenText() {
    const tokenBox = document.getElementById('tokenBox');
    if (!tokenBox) return;
    
    const range = document.createRange();
    range.selectNodeContents(tokenBox);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
}

function fallbackCopy(text, btn) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '-9999px';
    
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        const successful = document.execCommand('copy');
        if (successful) {
            showCopySuccess(btn);
        } else {
            showCopyError(btn);
        }
    } catch (err) {
        console.error('Fallback copy failed:', err);
        showCopyError(btn);
    }
    
    document.body.removeChild(textArea);
}

function showCopySuccess(btn) {
    if (!btn) return;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<span class="material-symbols-outlined" style="font-size: 18px; margin-right: 8px;">check</span> Copied!';
    btn.style.background = 'var(--md-sys-color-success-container)';
    btn.style.color = 'var(--md-sys-color-on-success-container)';
    
    setTimeout(() => {
        btn.innerHTML = originalHTML;
        btn.style.background = '';
        btn.style.color = '';
    }, 2000);
}

function showCopyError(btn) {
    if (!btn) return;
    
    selectTokenText();
    
    btn.innerHTML = '<span class="material-symbols-outlined" style="font-size: 18px; margin-right: 8px;">info</span> Press Ctrl+C';
    btn.style.background = 'var(--md-sys-color-secondary-container)';
    btn.style.color = 'var(--md-sys-color-on-secondary-container)';
    
    setTimeout(() => {
        btn.innerHTML = '<span class="material-symbols-outlined" style="font-size: 18px; margin-right: 8px;">content_copy</span> Copy Token';
        btn.style.background = '';
        btn.style.color = '';
    }, 3000);
}

function showSuccess(token) {
    const result = document.getElementById('result');
    
    const container = document.createElement('div');
    container.className = 'result success';
    
    const strong = document.createElement('strong');
    strong.textContent = 'Success!';
    container.appendChild(strong);
    container.appendChild(document.createElement('br'));
    container.appendChild(document.createElement('br'));
    container.appendChild(document.createTextNode('Your master token:'));
    container.appendChild(document.createElement('br'));
    
    const tokenBox = document.createElement('div');
    tokenBox.className = 'token-box';
    tokenBox.id = 'tokenBox';
    tokenBox.textContent = token;
    tokenBox.style.cursor = 'pointer';
    tokenBox.title = 'Click to select';
    tokenBox.addEventListener('click', selectTokenText);
    container.appendChild(tokenBox);
    
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'copy-btn';
    copyBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size: 18px; margin-right: 8px;">content_copy</span> Copy Token';
    copyBtn.addEventListener('click', copyToken);
    container.appendChild(copyBtn);
    
    const small = document.createElement('small');
    small.textContent = 'Copy master token to GoogleKeepFlow settings.';
    container.appendChild(small);
    
    result.innerHTML = '';
    result.appendChild(container);
}

function showError(message) {
    const result = document.getElementById('result');
    const container = document.createElement('div');
    container.className = 'result error';
    
    const strong = document.createElement('strong');
    strong.textContent = 'Error: ';
    container.appendChild(strong);
    container.appendChild(document.createTextNode(message));
    
    result.innerHTML = '';
    result.appendChild(container);
}

document.getElementById('tokenForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value.replace(/\s/g, '');
    const btn = document.getElementById('submitBtn');
    const result = document.getElementById('result');

    btn.disabled = true;
    btn.textContent = 'Getting challenge...';
    result.innerHTML = '';

    try {
        const challengeRes = await fetch('/api/challenge');
        const challengeData = await challengeRes.json();

        if (!challengeData.success) {
            throw new Error(challengeData.error);
        }

        btn.textContent = 'Solving challenge...';
        const nonce = await solveChallenge(challengeData.challenge, challengeData.difficulty);

        btn.textContent = 'Requesting token...';
        const tokenRes = await fetch('/api/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: email,
                password: password,
                challenge_token: challengeData.token,
                nonce: nonce
            })
        });

        const tokenData = await tokenRes.json();

        if (tokenData.success) {
            showSuccess(tokenData.master_token);
        } else {
            showError(tokenData.error);
        }
    } catch (err) {
        showError(err.message);
    }

    btn.disabled = false;
    btn.textContent = 'Get Token';
});