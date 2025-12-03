(() => {
  window.__human_touched = false;
  window.__originalBackground = document.body?.style.backgroundColor || '';

  let humanInteractionTimeout;

  // Insert bot logo once
  if (!window.__botLogo) {
    const img = document.createElement('img');
    img_src =
      'https://github.com/lookr-fyi/job-application-bot-by-ollama-ai/blob/main/src/logo-large.png?raw=true';
    img.src = img_src;
    img.id = '__botLogo';
    img.style.width = '60px';
    img.style.height = '60px';
    img.style.zIndex = '999999';
    img.style.transition = 'transform 0.2s ease';
    img.style.pointerEvents = 'none';
    img.style.opacity = '0.9';
    img.style.display = 'none';
    window.__botLogo = img;

    // Label
    const label = document.createElement('div');
    label.id = '__botLabel';
    label.innerText = '';
    label.style.color = '#222222';
    label.style.fontSize = '14px';
    label.style.fontFamily = 'sans-serif';
    label.style.zIndex = '999999';
    label.style.background = '#FFE600';
    label.style.padding = '2px 6px';
    label.style.borderRadius = '4px';
    label.style.boxShadow = '0 1px 4px rgba(0,0,0,0.2)';
    label.style.display = 'none';
    window.__botLabel = label;

    const container = document.createElement('div');
    // add label and img to container and make them aligned center
    container.appendChild(img);
    container.appendChild(label);

    container.style.position = 'fixed';
    container.style.bottom = '20px';
    container.style.left = '20px';
    container.style.zIndex = '999999';
    container.style.display = 'flex';
    container.style.flexDirection = 'column'; // Stack vertically
    // add space between label and img
    container.style.gap = '5px';
    container.style.alignItems = 'center';
    container.style.justifyContent = 'center';
    document.body.appendChild(container);
    window.__botContainer = container;

    // Inject bounce animation - use textContent instead of innerHTML for Trusted Types
    const style = document.createElement('style');
    style.textContent = `
            @keyframes botBounce {
                0%   { transform: translateY(0); }
                10%  { transform: translateY(-30px); }
                20%  { transform: translateY(0); }
                30%  { transform: translateY(-20px); }
                40%  { transform: translateY(0); }
                50%  { transform: translateY(-10px); }
                60%  { transform: translateY(0); }
                100% { transform: translateY(0); }
            }
        `;
    document.head.appendChild(style);
  }

  const startBounce = () => {
    const img = window.__botLogo;
    img.style.display = 'block';
    img.style.animation = 'botBounce 2s infinite';
  };

  const stopBounce = () => {
    const img = window.__botLogo;
    if (img) {
      img.style.animation = 'none';
      img.style.display = 'none';
    }
  };

  // Show status
  const setStatus = (text, color) => {
    const label = window.__botLabel;
    label.innerText = text;
    label.style.display = 'block';
    label.style.color = color || '#222222';
  };

  startBounce();
  setStatus('Running...', '#222222');

  // Human interaction
  ['click', 'input', 'pause_event'].forEach(eventName => {
    window.addEventListener(
      eventName,
      () => {
        // Clear any existing timeout to prevent multiple triggers
        clearTimeout(humanInteractionTimeout);

        // Set a new timeout to call stopBounce() after 400ms
        humanInteractionTimeout = setTimeout(() => {
          window.__human_touched = true;
          console.log('👤 Human interaction detected:', eventName);
          stopBounce();
          setStatus('Paused...', '#808080');
        }, 400);
      },
      true
    );
  });

  // Playwright interaction
  window.addEventListener('playwright-bot', () => {
    // Clear the timeout to prevent stopBounce() from being called
    clearTimeout(humanInteractionTimeout);

    window.__human_touched = false;
    console.log('Playwright (bot) interaction registered');
    startBounce();
    setStatus('Running...', '#222222');
  });
})();
