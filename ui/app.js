/**
 * Sims 4 Mod Auto Updater v0.1.5 - Web UI & pywebview Bridge Controller
 */

const DEFAULT_MODS = [];

// 상태별 심즈4 로딩 화면 스타일 위트 멘트 사전
const SIMS4_QUOTES = {
  scan: [
    '🦙 모드 폴더에서 길 잃은 라마 찾는 중...',
    '🧹 CC템 먼지 털어내는 중...',
    '🤝 스크립트 모드들이 사이좋게 지내는지 확인 중...',
    '🕵️ 벨라 고트의 행방을 추적하는 중...',
    '🔭 망원경으로 이웃집 정원을 관찰하는 중...',
  ],
  update: [
    '🧪 최신 패치 노트에 맞춰 마법의 물약 조제 중...',
    '💎 플럼밥 광택 내는 중...',
    '🦙 라마에게 특식 먹이를 주는 중...',
    '📐 스플라인 곡선을 정교하게 다듬는 중...',
    '🧀 구운 치즈 샌드위치를 완벽하게 굽는 중...',
    '🌱 소 식물의 케이크 미끼를 감추는 중...',
    '♟️ 죽음의 신과 체스 필승법을 연구하는 중...',
  ],
  complete: [
    '💎 준비 완료! 이제 플럼밥을 띄울 시간입니다!',
    '✨ 모든 모드가 반짝반짝 윤이 납니다.',
  ],
  error: [
    '🔥 앗! 누군가 토스트기를 고장 냈네요. 연결을 확인해 주세요.',
  ],
};

document.addEventListener('DOMContentLoaded', () => {
  const appContainer = document.getElementById('app-container');
  const modListLabel = document.getElementById('mod-list-label');
  const modListContainer = document.getElementById('mod-list-section');
  const modList = document.getElementById('mod-list');
  const backupBtn = document.getElementById('btn-backup');
  const refreshBtn = document.getElementById('btn-refresh');
  const modFolderPath = document.getElementById('mod-folder-path');
  const changeFolderBtn = document.getElementById('btn-change-folder');
  const selectAllCheckbox = document.getElementById('select-all-mods');
  const searchInput = document.getElementById('mod-search-input');
  const clearSearchBtn = document.getElementById('btn-clear-search');
  const statusSummary = document.getElementById('status-summary');
  const autoLaunchCheckbox = document.getElementById('chk-auto-launch');
  const wittyQuoteEl = document.getElementById('witty-quote');
  const progressBar = document.getElementById('progress-bar');
  const logBox = document.getElementById('log-box');
  const updateBtn = document.getElementById('btn-update');
  const orbCountBadge = document.getElementById('orb-count-badge');
  const orbMainText = document.getElementById('orb-main-text');
  const orbSubText = document.getElementById('orb-sub-text');
  const loaderIndicator = document.getElementById('loader-indicator');
  const loaderText = document.getElementById('loader-text');

  // 무드렛 대시보드 카운트 & 카드 그리드 요소
  const countTotalEl = document.getElementById('count-total');
  const countUpdateEl = document.getElementById('count-update');
  const countConflictEl = document.getElementById('count-conflict');
  const countLatestEl = document.getElementById('count-latest');
  const moodletGrid = document.getElementById('moodlet-grid');

  let currentMods = [];
  let currentFilter = 'all'; // 'all' | 'update' | 'error' | 'latest'
  let searchQuery = '';
  let isBusy = false;
  let isInitializing = true;
  let quoteIntervalId = null;
  let quoteIndex = 0;
  let completeQuoteIdx = 0;

  // 전체 창에서 불필요한 드래그/스크롤 이벤트 방지 (모드 목록 컨테이너 내부만 세로 스크롤 허용)
  window.addEventListener(
    'wheel',
    (event) => {
      if (!modListContainer.contains(event.target)) {
        event.preventDefault();
      }
    },
    { passive: false }
  );

  const hasPywebview = () =>
    Boolean(window.pywebview && window.pywebview.api);

  // 심즈4 위트 멘트 표시 및 롤링 제어
  const setWittyQuote = (text, tone = 'info') => {
    if (!wittyQuoteEl) return;
    wittyQuoteEl.classList.add('is-rolling');
    setTimeout(() => {
      wittyQuoteEl.textContent = text;
      wittyQuoteEl.classList.remove('is-complete', 'is-error');
      if (tone === 'complete') {
        wittyQuoteEl.classList.add('is-complete');
      } else if (tone === 'error') {
        wittyQuoteEl.classList.add('is-error');
      }
      wittyQuoteEl.classList.remove('is-rolling');
    }, 150);
  };

  const startWittyQuoteRolling = (category = 'update') => {
    stopWittyQuoteRolling(null);
    const pool = SIMS4_QUOTES[category] || SIMS4_QUOTES.update;
    quoteIndex = 0;
    setWittyQuote(pool[quoteIndex], 'info');
    quoteIntervalId = setInterval(() => {
      quoteIndex = (quoteIndex + 1) % pool.length;
      setWittyQuote(pool[quoteIndex], 'info');
    }, 1050);
  };

  const getNextCompleteQuote = () => {
    const quote = SIMS4_QUOTES.complete[completeQuoteIdx % SIMS4_QUOTES.complete.length];
    completeQuoteIdx += 1;
    return quote;
  };

  const stopWittyQuoteRolling = (finalQuote, tone = 'complete') => {
    if (quoteIntervalId) {
      clearInterval(quoteIntervalId);
      quoteIntervalId = null;
    }
    if (finalQuote) {
      setWittyQuote(finalQuote, tone);
    }
  };

  // 작업 진행 중 중복 클릭(레이스 컨디션) 방지용 전체 컨트롤 잠금/해제
  const applyBusyLockState = () => {
    if (backupBtn) backupBtn.disabled = isBusy;
    if (refreshBtn) refreshBtn.disabled = isBusy;
    if (changeFolderBtn) changeFolderBtn.disabled = isBusy;
    if (selectAllCheckbox) selectAllCheckbox.disabled = isBusy;

    if (modList) {
      modList.querySelectorAll('.mod-item-checkbox').forEach((cb) => {
        const mod = currentMods.find((m) => m.id === cb.dataset.modId);
        cb.disabled = isBusy || Boolean(mod?.disabled);
      });
      modList
        .querySelectorAll('.btn-item-update.is-updatable, .btn-item-update.is-manual, .btn-item-update.is-conflict')
        .forEach((btn) => {
          btn.disabled = isBusy;
        });
    }

    syncSelectionState();
  };

  const setLoading = (
    isLoading,
    message = '플럼밥이 모드를 탐색 중...',
    options = {}
  ) => {
    const {
      category = 'scan',
      doneQuote = getNextCompleteQuote(),
      tone = 'complete',
    } = options;

    isBusy = isLoading;

    if (loaderIndicator) {
      if (loaderText) {
        loaderText.textContent = message;
      }
      loaderIndicator.classList.toggle('is-hidden', !isLoading);
    }

    applyBusyLockState();

    if (isLoading) {
      startWittyQuoteRolling(category);
    } else {
      stopWittyQuoteRolling(doneQuote, tone);
    }
  };

  const setLog = (message) => {
    if (logBox) {
      logBox.textContent = `> ${message}`;
      logBox.title = message;
    }
  };

  // 상태 타입별 무드렛 CSS 클래스 매핑
  const getStatusClass = (statusType) => {
    switch (statusType) {
      case 'update':
        return 'status-update';
      case 'checking':
        return 'status-checking';
      case 'latest':
        return 'status-latest';
      case 'manual':
        return 'status-manual';
      case 'outdated':
        return 'status-outdated';
      case 'error':
      case 'conflict':
        return 'status-error';
      default:
        return 'status-update';
    }
  };

  // 무드렛 필터 + 실시간 검색어 매칭 함수
  const matchesFilterAndSearch = (mod) => {
    if (
      currentFilter === 'update' &&
      mod.statusType !== 'update' &&
      mod.statusType !== 'outdated' &&
      mod.statusType !== 'manual'
    ) {
      return false;
    }
    if (currentFilter === 'error' && mod.statusType !== 'error' && mod.statusType !== 'conflict') {
      return false;
    }
    if (currentFilter === 'latest' && mod.statusType !== 'latest') {
      return false;
    }

    if (searchQuery.trim() !== '') {
      const q = searchQuery.trim().toLowerCase();
      const nameMatch = (mod.name || '').toLowerCase().includes(q);
      const authorMatch = (mod.author || '').toLowerCase().includes(q);
      const versionMatch =
        (mod.currentVersion || '').toLowerCase().includes(q) ||
        (mod.latestVersion || '').toLowerCase().includes(q);
      return nameMatch || authorMatch || versionMatch;
    }

    return true;
  };

  // 심즈4 감정 무드렛 대시보드 수치 업데이트
  const updateDashboard = () => {
    const totalCount = currentMods.length;
    const updateCount = currentMods.filter(
      (m) =>
        m.statusType === 'update' ||
        m.statusType === 'outdated' ||
        m.statusType === 'manual'
    ).length;
    const conflictCount = currentMods.filter(
      (m) => m.statusType === 'error' || m.statusType === 'conflict'
    ).length;
    const latestCount = currentMods.filter((m) => m.statusType === 'latest').length;

    if (countTotalEl) countTotalEl.textContent = String(totalCount);
    if (countUpdateEl) countUpdateEl.textContent = String(updateCount);
    if (countConflictEl) countConflictEl.textContent = String(conflictCount);
    if (countLatestEl) countLatestEl.textContent = String(latestCount);

    if (modListLabel) {
      modListLabel.textContent = `업데이트 대상 목록 (총 ${totalCount}개 / 업데이트 가능 ${updateCount}개)`;
    }

    if (moodletGrid) {
      moodletGrid.querySelectorAll('.moodlet-card').forEach((card) => {
        card.classList.toggle('is-active', card.dataset.filter === currentFilter);
      });
    }
  };

  // 심즈4 갤러리 카드 스타일 모드 목록 렌더링
  const renderModList = (mods = currentMods) => {
    if (!modList) return;
    currentMods = mods;
    updateDashboard();

    const filteredMods = currentMods.filter((mod) => matchesFilterAndSearch(mod));
    modList.innerHTML = '';

    if (filteredMods.length === 0) {
      const emptyEl = document.createElement('div');
      emptyEl.className = 'empty-filter-state';
      if (currentMods.length === 0) {
        emptyEl.textContent = isInitializing
          ? '모드 폴더에서 설치된 모드를 불러오는 중입니다...'
          : '선택된 Mods 폴더에 설치된 스크립트/게임플레이 모드가 없습니다.';
      } else if (searchQuery.trim() !== '') {
        emptyEl.textContent = `"${searchQuery.trim()}" 검색 결과가 없습니다.`;
      } else {
        emptyEl.textContent = '해당 무드렛 상태의 모드가 없습니다.';
      }
      modList.appendChild(emptyEl);
      syncSelectionState();
      return;
    }

    filteredMods.forEach((mod) => {
      const cardEl = document.createElement('article');
      cardEl.className = `mod-gallery-card${mod.disabled ? ' is-disabled' : ''}`;
      cardEl.dataset.modId = mod.id;
      cardEl.dataset.status = mod.statusType;

      // 좌측 영역: 체크박스 + (모드 이름, 제작자 배지, 현재 버전 → 최신 버전)
      const leftEl = document.createElement('div');
      leftEl.className = 'mod-card-left';

      const checkboxEl = document.createElement('input');
      checkboxEl.type = 'checkbox';
      checkboxEl.className = 'mod-checkbox mod-item-checkbox';
      checkboxEl.checked = Boolean(mod.checked && !mod.disabled);
      checkboxEl.disabled = isBusy || Boolean(mod.disabled);
      checkboxEl.dataset.modId = mod.id;
      checkboxEl.id = `mod-check-${mod.id}`;

      const infoEl = document.createElement('div');
      infoEl.className = 'mod-card-info';

      const titleRowEl = document.createElement('div');
      titleRowEl.className = 'mod-card-title-row';

      const nameLabelEl = document.createElement('label');
      nameLabelEl.className = 'mod-name';
      nameLabelEl.htmlFor = `mod-check-${mod.id}`;
      nameLabelEl.textContent = mod.name;
      nameLabelEl.title = mod.name;

      titleRowEl.appendChild(nameLabelEl);

      const metaRowEl = document.createElement('div');
      metaRowEl.className = 'mod-card-meta-row';

      const authorBadgeEl = document.createElement('span');
      authorBadgeEl.className = 'mod-author-badge';
      authorBadgeEl.textContent = `👤 ${mod.author || '미상'}`;

      const versionEl = document.createElement('span');
      versionEl.className = 'version-text mod-version';
      versionEl.textContent = `${mod.currentVersion} → ${mod.latestVersion}`;

      metaRowEl.appendChild(authorBadgeEl);
      metaRowEl.appendChild(versionEl);

      infoEl.appendChild(titleRowEl);
      infoEl.appendChild(metaRowEl);

      leftEl.appendChild(checkboxEl);
      leftEl.appendChild(infoEl);

      // 우측 영역: 상태 무드렛 배지 + 상태별 맞춤 액션 버튼
      const rightEl = document.createElement('div');
      rightEl.className = 'mod-card-right';

      const statusEl = document.createElement('span');
      statusEl.className = `mod-status ${getStatusClass(mod.statusType)}`.trim();
      statusEl.textContent = mod.statusText;

      const actionBtn = document.createElement('button');
      actionBtn.type = 'button';
      actionBtn.dataset.modId = mod.id;

      if (mod.statusType === 'update' || mod.statusType === 'outdated') {
        actionBtn.className = 'sim-btn btn-item-update is-updatable';
        actionBtn.textContent = '업데이트';
        actionBtn.disabled = isBusy;
      } else if (mod.statusType === 'manual') {
        actionBtn.className = 'sim-btn btn-item-update is-manual';
        actionBtn.textContent = '페이지 열기';
        actionBtn.disabled = isBusy;
      } else if (mod.statusType === 'conflict') {
        actionBtn.className = 'sim-btn btn-item-update is-conflict';
        actionBtn.textContent = '폴더 열기';
        actionBtn.disabled = isBusy;
      } else if (mod.statusType === 'checking') {
        actionBtn.className = 'sim-btn btn-item-update is-checking';
        actionBtn.textContent = '확인 중...';
        actionBtn.disabled = true;
      } else if (mod.statusType === 'latest') {
        actionBtn.className = 'sim-btn btn-item-update is-latest';
        actionBtn.textContent = '최신 완료';
        actionBtn.disabled = true;
      } else {
        actionBtn.className = 'sim-btn btn-item-update is-error';
        actionBtn.textContent = '점검 필요';
        actionBtn.disabled = true;
      }

      rightEl.appendChild(statusEl);
      rightEl.appendChild(actionBtn);

      cardEl.appendChild(leftEl);
      cardEl.appendChild(rightEl);

      modList.appendChild(cardEl);
    });

    syncSelectionState();
  };

  // 체크박스 및 우측 하단 거대 초록 원형 버튼('모두 업데이트' ↔ '심즈4 바로 실행') 동기화
  const syncSelectionState = () => {
    const selectableVisibleMods = currentMods.filter(
      (m) => !m.disabled && matchesFilterAndSearch(m)
    );
    const selectableVisibleChecked = selectableVisibleMods.filter((m) => m.checked).length;

    if (selectAllCheckbox) {
      if (selectableVisibleMods.length === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
      } else {
        selectAllCheckbox.checked = selectableVisibleChecked === selectableVisibleMods.length;
        selectAllCheckbox.indeterminate =
          selectableVisibleChecked > 0 &&
          selectableVisibleChecked < selectableVisibleMods.length;
      }
    }

    const totalCheckedCount = currentMods.filter((m) => !m.disabled && m.checked).length;
    const autoLaunch = autoLaunchCheckbox ? autoLaunchCheckbox.checked : true;

    if (totalCheckedCount > 0) {
      if (orbCountBadge) {
        orbCountBadge.textContent = `${totalCheckedCount}개`;
        orbCountBadge.classList.remove('is-launch-mode');
      }
      if (orbMainText) {
        orbMainText.textContent = '모두 업데이트';
      }
      if (orbSubText) {
        orbSubText.textContent = autoLaunch ? '& 심즈4 실행' : '선택 일괄 적용';
      }
    } else {
      if (orbCountBadge) {
        orbCountBadge.textContent = 'PLAY';
        orbCountBadge.classList.add('is-launch-mode');
      }
      if (orbMainText) {
        orbMainText.textContent = '심즈4 실행';
      }
      if (orbSubText) {
        orbSubText.textContent = '바로 플레이';
      }
    }

    if (updateBtn) {
      updateBtn.disabled = isBusy;
      updateBtn.classList.toggle('is-disabled', isBusy);
      updateBtn.setAttribute(
        'aria-label',
        totalCheckedCount > 0
          ? `모두 업데이트 (${totalCheckedCount}개 선택됨)`
          : '심즈4 바로 실행'
      );
    }

    if (!isBusy && statusSummary) {
      statusSummary.textContent =
        totalCheckedCount > 0
          ? `진행 상태: 대기 중 (0 / ${totalCheckedCount})`
          : '진행 상태: 모든 선택 완료 (바로 실행 가능)';
    }
  };

  if (autoLaunchCheckbox) {
    autoLaunchCheckbox.addEventListener('change', () => {
      syncSelectionState();
    });
  }

  // 무드렛 카드 클릭 필터 연동
  const setFilter = (nextFilter) => {
    if (!nextFilter) return;
    currentFilter = nextFilter;
    if (!isBusy) {
      if (nextFilter === 'error') {
        const hasError = currentMods.some(
          (m) => m.statusType === 'error' || m.statusType === 'conflict'
        );
        if (hasError) setWittyQuote(SIMS4_QUOTES.error[0], 'error');
      } else if (nextFilter === 'latest') {
        setWittyQuote(SIMS4_QUOTES.complete[1], 'complete');
      }
    }
    renderModList(currentMods);
  };

  if (moodletGrid) {
    moodletGrid.addEventListener('click', (event) => {
      const card = event.target.closest('.moodlet-card');
      if (card && card.dataset.filter) {
        setFilter(card.dataset.filter);
      }
    });
  }

  // 실시간 검색창 입력 연동
  if (searchInput) {
    searchInput.addEventListener('input', (event) => {
      searchQuery = event.target.value || '';
      if (clearSearchBtn) {
        clearSearchBtn.classList.toggle('is-hidden', searchQuery.length === 0);
      }
      renderModList(currentMods);
    });
  }

  if (clearSearchBtn && searchInput) {
    clearSearchBtn.addEventListener('click', () => {
      searchQuery = '';
      searchInput.value = '';
      clearSearchBtn.classList.add('is-hidden');
      searchInput.focus();
      renderModList(currentMods);
    });
  }

  // 전체 선택 체크박스 이벤트
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', (event) => {
      if (isBusy) return;
      const isChecked = event.target.checked;
      currentMods.forEach((mod) => {
        if (!mod.disabled && matchesFilterAndSearch(mod)) {
          mod.checked = isChecked;
        }
      });
      renderModList(currentMods);
    });
  }

  // 백엔드 원격 병렬 스캔 실행 함수
  const runRemoteScan = async () => {
    if (!hasPywebview() || isBusy) return;
    setLoading(true, '플럼밥이 원격 최신 버전을 병렬 탐색 중...', { category: 'scan' });
    if (progressBar) progressBar.style.width = '8%';

    try {
      const res = await window.pywebview.api.scan_mods(true);
      if (res?.error) {
        setLog(`스캔 오류: ${res.error}`);
        setLoading(false, '', {
          doneQuote: SIMS4_QUOTES.error[0],
          tone: 'error',
        });
        return;
      }
      if (Array.isArray(res?.mods)) {
        isInitializing = false;
        renderModList(res.mods);
      }
      if (progressBar) progressBar.style.width = '100%';
      setLog(res?.message || '원격 버전 목록 확인이 완료되었습니다.');
      setLoading(false, '', {
        doneQuote: getNextCompleteQuote(),
        tone: 'complete',
      });
    } catch (err) {
      setLog(`스캔 중 오류가 발생했습니다: ${err}`);
      setLoading(false, '', {
        doneQuote: SIMS4_QUOTES.error[0],
        tone: 'error',
      });
    }
  };

  // 심즈4 단독 실행 함수 (0개 선택 상태에서 원형 버튼 클릭 시)
  const launchSims4Directly = async () => {
    if (isBusy) return;
    setLog('심즈4(The Sims 4) 게임을 실행하고 있습니다...');
    setWittyQuote(SIMS4_QUOTES.complete[0], 'complete');

    if (hasPywebview()) {
      try {
        const res = await window.pywebview.api.launch_sims4();
        if (res?.ok) {
          setLog(res.message || '심즈4를 실행했습니다! 즐거운 플레이 되세요!');
        } else {
          setLog(res?.error || '심즈4 실행 파일을 찾지 못했습니다.');
          setWittyQuote(SIMS4_QUOTES.error[0], 'error');
        }
      } catch (err) {
        setLog(`심즈4 실행 오류: ${err}`);
        setWittyQuote(SIMS4_QUOTES.error[0], 'error');
      }
    } else {
      setLog('데스크톱 앱(pywebview) 환경에서 심즈4(TS4_x64.exe)가 바로 실행됩니다!');
    }
  };

  // 수동 확인 모드 공식 페이지 열기
  const openModPage = async (modId) => {
    const target = currentMods.find((m) => m.id === modId);
    if (hasPywebview()) {
      try {
        const res = await window.pywebview.api.open_mod_page(modId);
        setLog(res?.message || res?.error || '공식 배포 페이지 열기를 요청했습니다.');
      } catch (err) {
        setLog(`페이지 열기 실패: ${err}`);
      }
    } else if (target?.pageUrl) {
      window.open(target.pageUrl, '_blank', 'noopener,noreferrer');
      setLog(`[${target.name}] 공식 배포 페이지를 브라우저 새 탭에서 열었습니다.`);
    }
  };

  // 충돌/중복 모드 폴더 열기
  const openModFolder = async (modId) => {
    const target = currentMods.find((m) => m.id === modId);
    if (hasPywebview()) {
      try {
        const res = await window.pywebview.api.open_mod_folder(modId);
        setLog(res?.message || res?.error || '폴더를 탐색기에서 열었습니다.');
      } catch (err) {
        setLog(`폴더 열기 실패: ${err}`);
      }
    } else if (target) {
      setLog(`[${target.name}] 데스크톱 앱 실행 시 중복 파일 위치가 Windows 탐색기에서 열립니다.`);
    }
  };

  // 모드 업데이트 실행 및 선택적 심즈4 런치
  const executeModUpdates = async (targetIds, launchGameAfter = false) => {
    if (isBusy || !targetIds || targetIds.length === 0) return;

    setLoading(true, '플럼밥이 업데이트 중...', { category: 'update' });
    if (progressBar) progressBar.style.width = '5%';

    if (hasPywebview()) {
      try {
        const res = await window.pywebview.api.update_selected_mods(
          targetIds,
          launchGameAfter
        );
        if (res?.error) {
          setLog(`업데이트 오류: ${res.error}`);
          setLoading(false, '', {
            doneQuote: SIMS4_QUOTES.error[0],
            tone: 'error',
          });
          return;
        }
        if (progressBar) progressBar.style.width = '100%';
        if (Array.isArray(res?.mods)) {
          renderModList(res.mods);
        }
        if (statusSummary) {
          statusSummary.textContent = `진행 상태: 완료 (${targetIds.length} / ${targetIds.length})`;
        }
        setLog(
          res?.message ||
            `선택한 ${targetIds.length}개 모드 업데이트가 완료되었습니다!`
        );
        setLoading(false, '', {
          doneQuote: getNextCompleteQuote(),
          tone: 'complete',
        });
      } catch (err) {
        setLog(`업데이트 중 오류가 발생했습니다: ${err}`);
        setLoading(false, '', {
          doneQuote: SIMS4_QUOTES.error[0],
          tone: 'error',
        });
      }
    } else {
      let completed = 0;
      const total = targetIds.length;
      for (const id of targetIds) {
        const target = currentMods.find((m) => m.id === id);
        setLog(`[${target ? target.name : id}] 최신 버전 다운로드 및 적용 중...`);
        await new Promise((r) => setTimeout(r, 800));
        completed += 1;
        const pct = Math.round((completed / total) * 100);
        if (progressBar) progressBar.style.width = `${pct}%`;
        if (statusSummary) {
          statusSummary.textContent = `진행 상태: 업데이트 중 (${completed} / ${total})`;
        }
      }
      const singleTargetName =
        currentMods.find((m) => m.id === targetIds[0])?.name || targetIds[0];
      const updatedMods = currentMods.map((mod) =>
        targetIds.includes(mod.id)
          ? {
              ...mod,
              currentVersion: mod.latestVersion,
              statusText: '최신버전',
              statusType: 'latest',
              checked: false,
            }
          : mod
      );
      renderModList(updatedMods);
      if (statusSummary) {
        statusSummary.textContent = `진행 상태: 완료 (${total} / ${total})`;
      }
      setLog(
        total === 1 && !launchGameAfter
          ? `[${singleTargetName}] 개별 업데이트가 완료되었습니다!`
          : launchGameAfter
          ? `선택한 ${total}개 모드 업데이트 완료! 심즈4(The Sims 4)를 실행합니다.`
          : `선택한 ${total}개 모드가 모두 최신 버전으로 업데이트되었습니다!`
      );
      setLoading(false, '', {
        doneQuote: getNextCompleteQuote(),
        tone: 'complete',
      });
    }
  };

  if (modList) {
    modList.addEventListener('change', (event) => {
      if (isBusy) return;
      if (event.target.classList.contains('mod-item-checkbox')) {
        const modId = event.target.dataset.modId;
        const targetMod = currentMods.find((m) => m.id === modId);
        if (targetMod && !targetMod.disabled) {
          targetMod.checked = event.target.checked;
        }
        syncSelectionState();
      }
    });

    modList.addEventListener('click', (event) => {
      if (isBusy) return;
      const actionBtn = event.target.closest('.btn-item-update');
      if (!actionBtn || actionBtn.disabled || !actionBtn.dataset.modId) return;

      const modId = actionBtn.dataset.modId;
      if (actionBtn.classList.contains('is-updatable')) {
        executeModUpdates([modId], false);
      } else if (actionBtn.classList.contains('is-manual')) {
        openModPage(modId);
      } else if (actionBtn.classList.contains('is-conflict')) {
        openModFolder(modId);
      }
    });
  }

  // 모드 폴더 백업 버튼 (CC 제외 빠른 핵심 모드 백업)
  if (backupBtn) {
    backupBtn.addEventListener('click', async () => {
      if (isBusy) return;
      setLoading(true, '플럼밥이 핵심 모드를 빠르게 백업 중...', { category: 'update' });
      setLog('대용량 CC 폴더를 제외하고 핵심 스크립트/게임플레이 모드를 백업 중입니다...');

      if (hasPywebview()) {
        try {
          const res = await window.pywebview.api.backup_mods_folder();
          if (res?.error) {
            setLog(`백업 실패: ${res.error}`);
            setLoading(false, '', {
              doneQuote: SIMS4_QUOTES.error[0],
              tone: 'error',
            });
          } else {
            setLog(res?.message || `모드 폴더 백업 완료: ${res?.backup_path || 'backups/'}`);
            setLoading(false, '', {
              doneQuote: getNextCompleteQuote(),
              tone: 'complete',
            });
          }
        } catch (err) {
          setLog(`백업 중 오류가 발생했습니다: ${err}`);
          setLoading(false, '', {
            doneQuote: SIMS4_QUOTES.error[0],
            tone: 'error',
          });
        }
      } else {
        setTimeout(() => {
          const now = new Date();
          const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(
            now.getDate()
          ).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(
            now.getMinutes()
          ).padStart(2, '0')}`;
          setLog(`핵심 모드 빠른 백업 완료! (backups/mods_core_${stamp} · CC 제외)`);
          setLoading(false, '', {
            doneQuote: getNextCompleteQuote(),
            tone: 'complete',
          });
        }, 1050);
      }
    });
  }

  // 새로고침(스캔) 버튼
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      if (isBusy) return;
      if (hasPywebview()) {
        await runRemoteScan();
      } else {
        setLoading(true, '플럼밥이 모드를 탐색 중...', { category: 'scan' });
        setLog('모드 폴더 및 원격 버전을 확인하고 있습니다...');
        setTimeout(() => {
          isInitializing = false;
          currentFilter = 'all';
          searchQuery = '';
          if (searchInput) searchInput.value = '';
          if (clearSearchBtn) clearSearchBtn.classList.add('is-hidden');
          renderModList(DEFAULT_MODS.map((m) => ({ ...m })));
          if (progressBar) progressBar.style.width = '0%';
          setLog('원격 버전 목록 확인이 완료되었습니다.');
          setLoading(false, '', {
            doneQuote: getNextCompleteQuote(),
            tone: 'complete',
          });
        }, 1250);
      }
    });
  }

  // 폴더 변경 버튼
  if (changeFolderBtn) {
    changeFolderBtn.addEventListener('click', async () => {
      if (isBusy) return;
      if (hasPywebview()) {
        try {
          const res = await window.pywebview.api.select_mods_folder();
          if (res?.cancelled) return;
          if (res?.error) {
            setLog(`폴더 변경 오류: ${res.error}`);
            setWittyQuote(SIMS4_QUOTES.error[0], 'error');
            return;
          }
          if (res?.mods_folder && modFolderPath) {
            modFolderPath.textContent = res.mods_folder;
            modFolderPath.title = res.mods_folder;
          }
          if (Array.isArray(res?.mods)) {
            isInitializing = false;
            currentFilter = 'all';
            renderModList(res.mods);
          }
          setLog(res?.message || '모드 폴더가 변경되었습니다.');
          if (res?.needs_remote_scan) {
            await runRemoteScan();
          }
        } catch (err) {
          setLog(`폴더 변경 중 오류가 발생했습니다: ${err}`);
          setWittyQuote(SIMS4_QUOTES.error[0], 'error');
        }
      } else {
        const currentPath = modFolderPath ? modFolderPath.textContent.trim() : '';
        const nextPath = window.prompt('변경할 심즈4 Mods 폴더 경로를 입력하세요:', currentPath);
        if (nextPath && nextPath.trim() && modFolderPath) {
          modFolderPath.textContent = nextPath.trim();
          modFolderPath.title = nextPath.trim();
          setLog(`모드 폴더 경로가 변경되었습니다: ${nextPath.trim()}`);
        }
      }
    });
  }

  // 우측 하단 거대 초록색 원형 메인 버튼 (1개 이상 선택 시 '모두 업데이트', 0개일 때 '심즈4 바로 실행')
  if (updateBtn) {
    updateBtn.addEventListener('click', async () => {
      if (isBusy) return;
      const selectedIds = currentMods
        .filter((m) => !m.disabled && m.checked)
        .map((m) => m.id);

      if (selectedIds.length === 0) {
        await launchSims4Directly();
        return;
      }

      const launchAfter = autoLaunchCheckbox ? autoLaunchCheckbox.checked : true;
      await executeModUpdates(selectedIds, launchAfter);
    });
  }

  // 초기 화면 렌더링 (하드코딩된 예시 데이터 없이 빈 로딩 상태로 시작 후 pywebview 준비 시 실제 로컬 폴더 반영)
  renderModList(currentMods);

  // pywebview 환경 준비 시 2단계 비차단 스캔 (1단계: 로컬 0.5초 즉시 표시 -> 2단계: 백그라운드 병렬 원격 조회)
  window.addEventListener('pywebviewready', async () => {
    if (!hasPywebview()) return;
    try {
      const state = await window.pywebview.api.get_initial_state();
      isInitializing = false;
      if (state?.mods_folder && modFolderPath) {
        modFolderPath.textContent = state.mods_folder;
        modFolderPath.title = state.mods_folder;
      }
      // 빈 폴더([])인 경우에도 가상 샘플 데이터를 남기지 않고 실제 상태를 그대로 반영
      if (Array.isArray(state?.mods)) {
        renderModList(state.mods);
      } else {
        renderModList([]);
      }
      if (state?.message) {
        setLog(state.message);
      }
      if (state?.cached) {
        if (progressBar) progressBar.style.width = '100%';
        setWittyQuote(getNextCompleteQuote(), 'complete');
      } else if (state?.needs_remote_scan) {
        await runRemoteScan();
      }
    } catch (_) {
      isInitializing = false;
      renderModList([]);
      setWittyQuote(SIMS4_QUOTES.error[0], 'error');
    }
  });

  const onBackendProgress = (payload) => {
    if (!payload) return;
    if (typeof payload.percent === 'number' && progressBar) {
      progressBar.style.width = `${payload.percent}%`;
    }
    if (
      typeof payload.completed === 'number' &&
      typeof payload.total === 'number' &&
      statusSummary
    ) {
      const actionLabel = payload.mode === 'scan' ? '원격 스캔 중' : '업데이트 중';
      statusSummary.textContent = `진행 상태: ${actionLabel} (${payload.completed} / ${payload.total})`;
    }
    if (payload.message) {
      setLog(payload.message);
    }
  };

  window.Sims4UpdaterUI = {
    appContainer,
    modListContainer,
    modList,
    backupBtn,
    refreshBtn,
    modFolderPath,
    changeFolderBtn,
    selectAllCheckbox,
    searchInput,
    statusSummary,
    autoLaunchCheckbox,
    wittyQuoteEl,
    progressBar,
    logBox,
    updateBtn,
    SIMS4_QUOTES,
    renderModList,
    syncSelectionState,
    setFilter,
    setLoading,
    onBackendProgress,
  };
});
