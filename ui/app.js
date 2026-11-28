/**
 * Sims 4 Mod Auto Updater v0.1.6 - Web UI & pywebview Bridge Controller
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
  scan_subfolder: [
    '📂 지정한 폴더 안의 항목만 집중 탐색하는 중...',
    '🔎 선택한 경로의 최신 배포 버전을 대조하는 중...',
    '💎 전체 폴더 대신 지정된 폴더만 빠르게 확인하는 중...',
  ],
  scan_ww_anim: [
    '🎞️ 지정한 폴더에서 WW 애니메이션 팩만 집중 탐색 중...',
    '💜 애니메이션 제작자 공식 배포처와 버전을 대조하는 중...',
    '✨ 바디·의상 CC는 건너뛰고 실제 WW 애니메이션만 선별 중...',
    '🎬 심들의 애니메이션 패키지 메타데이터를 읽는 중...',
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
  const modListWrapper = document.getElementById('mod-list-wrapper');
  const modListContainer = document.getElementById('mod-list-section');
  const modList = document.getElementById('mod-list');
  const scrollUpBtn = document.getElementById('btn-scroll-up');
  const scrollDownBtn = document.getElementById('btn-scroll-down');
  const backupBtn = document.getElementById('btn-backup');
  const refreshBtn = document.getElementById('btn-refresh');
  const modFolderPath = document.getElementById('mod-folder-path');
  const pathScopeBadge = document.getElementById('path-scope-badge');
  const selectSubfolderBtn = document.getElementById('btn-select-subfolder');
  const resetSubfolderBtn = document.getElementById('btn-reset-subfolder');
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
  const totalMoodletLabelEl = document.querySelector('.moodlet-total .moodlet-label');
  const countUpdateEl = document.getElementById('count-update');
  const countConflictEl = document.getElementById('count-conflict');
  const countErrorEl = document.getElementById('count-error');
  const countLatestEl = document.getElementById('count-latest');
  const moodletGrid = document.getElementById('moodlet-grid');
  const optionSelectModal = document.getElementById('option-select-modal');
  const optionModalTitle = document.getElementById('option-modal-title');
  const optionModalDesc = document.getElementById('option-modal-desc');
  const optionModalList = document.getElementById('option-modal-list');
  const optionModalCloseBtn = document.getElementById('btn-option-modal-close');
  const optionModalCancelBtn = document.getElementById('btn-option-modal-cancel');
  const optionModalConfirmBtn = document.getElementById('btn-option-modal-confirm');

  let currentMods = [];
  let currentFilter = 'all'; // 'all' | 'update' | 'error' | 'latest'
  let searchQuery = '';
  let isBusy = false;
  let busyMode = ''; // '' | 'scan' | 'update'
  let activeScanToken = 0;
  let activeScopeState = {
    modsFolder: '',
    scanSubfolder: '',
    scanTargetPath: '',
    isScoped: false,
    isWwAnimScope: false,
    shortLabel: '',
    fullLabel: '',
  };
  let isInitializing = true;
  let quoteIntervalId = null;
  let quoteIndex = 0;
  let completeQuoteIdx = 0;

  // 전체 창에서 불필요한 드래그/스크롤 이벤트 방지 (모드 목록 및 옵션 모달 내부만 세로 스크롤 허용)
  window.addEventListener(
    'wheel',
    (event) => {
      if (optionSelectModal && !optionSelectModal.classList.contains('is-hidden')) {
        if (!optionModalList || !optionModalList.contains(event.target)) {
          event.preventDefault();
        }
        return;
      }
      const scrollArea = modListWrapper || modListContainer;
      if (!scrollArea || !scrollArea.contains(event.target)) {
        event.preventDefault();
      }
    },
    { passive: false }
  );

  // 모드 목록 위/아래 스크롤 화살표 표시 상태 갱신 및 클릭/길게 누르기/더블클릭 제어
  const updateScrollArrows = () => {
    if (!modListContainer) return;
    const { scrollTop, clientHeight, scrollHeight } = modListContainer;
    const canScrollUp = scrollTop > 4;
    const canScrollDown = scrollTop + clientHeight < scrollHeight - 4;
    if (scrollUpBtn) {
      scrollUpBtn.classList.toggle('is-hidden', !canScrollUp);
    }
    if (scrollDownBtn) {
      scrollDownBtn.classList.toggle('is-hidden', !canScrollDown);
    }
  };

  const bindScrollArrow = (btn, direction) => {
    if (!btn || !modListContainer) return;
    let holdTimeoutId = null;
    let holdIntervalId = null;
    let didHoldScroll = false;

    const stopHold = () => {
      if (holdTimeoutId) {
        clearTimeout(holdTimeoutId);
        holdTimeoutId = null;
      }
      if (holdIntervalId) {
        clearInterval(holdIntervalId);
        holdIntervalId = null;
      }
    };

    btn.addEventListener('mousedown', (event) => {
      if (event.button !== 0) return;
      didHoldScroll = false;
      stopHold();
      holdTimeoutId = setTimeout(() => {
        didHoldScroll = true;
        holdIntervalId = setInterval(() => {
          modListContainer.scrollTop += direction * 24;
          updateScrollArrows();
        }, 32);
      }, 240);
    });

    ['mouseup', 'mouseleave', 'blur'].forEach((evt) => {
      btn.addEventListener(evt, stopHold);
    });

    btn.addEventListener('click', () => {
      if (didHoldScroll) {
        didHoldScroll = false;
        return;
      }
      modListContainer.scrollBy({ top: direction * 170, behavior: 'smooth' });
    });

    btn.addEventListener('dblclick', (event) => {
      event.preventDefault();
      stopHold();
      modListContainer.scrollTo({
        top: direction < 0 ? 0 : modListContainer.scrollHeight,
        behavior: 'smooth',
      });
    });
  };

  if (modListContainer) {
    modListContainer.addEventListener('scroll', updateScrollArrows, { passive: true });
  }
  bindScrollArrow(scrollUpBtn, -1);
  bindScrollArrow(scrollDownBtn, 1);
  window.addEventListener('resize', () => requestAnimationFrame(updateScrollArrows));

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

  const extractLeafName = (rawPath) => {
    const parts = String(rawPath || '')
      .replace(/\//g, '\\')
      .split('\\')
      .map((s) => s.trim())
      .filter(Boolean);
    return parts.length > 0 ? parts[parts.length - 1] : '';
  };

  const detectWwAnimPathHint = (text) => {
    const low = String(text || '').toLowerCase();
    if (!low) return false;
    return (
      low.includes('wicked') ||
      low.includes('위키드') ||
      low.includes('anim') ||
      low.includes('motion') ||
      low.includes('nsfw') ||
      low.includes('woohoo') ||
      low.includes('19금') ||
      low.includes('꾸금') ||
      low.includes('후방') ||
      low.includes('우후') ||
      low.includes('사랑나누기') ||
      low.includes('성인모드') ||
      low.includes('성인애니') ||
      low.includes('성인모션') ||
      low.includes('야스') ||
      low.includes('애니') ||
      low.includes('모션') ||
      low.includes('동작') ||
      low.includes('체위') ||
      low.includes('포즈') ||
      low.includes('pose') ||
      /(?:^|[\s_\-\[\(\\])ww(?:$|[\s_\-\]\(\\]|[가-힣])/.test(low)
    );
  };

  const getScanQuoteCategory = () => {
    if (!activeScopeState.isScoped) return 'scan';
    return activeScopeState.isWwAnimScope ? 'scan_ww_anim' : 'scan_subfolder';
  };

  const getScopeLoadingMessage = (phase = 'remote') => {
    if (!activeScopeState.isScoped) {
      return phase === 'local'
        ? '플럼밥이 모드 폴더를 탐색 중...'
        : '플럼밥이 원격 최신 버전을 병렬 탐색 중...';
    }
    const label = activeScopeState.shortLabel || activeScopeState.fullLabel || '지정 폴더';
    if (activeScopeState.isWwAnimScope) {
      return phase === 'local'
        ? `[${label}] WW 애니메이션 폴더를 확인 중...`
        : `[${label}] WW 애니메이션 최신 버전 탐색 중...`;
    }
    return phase === 'local'
      ? `[${label}] 지정 폴더 항목을 확인 중...`
      : `[${label}] 지정 폴더 최신 버전 탐색 중...`;
  };

  // 경로 바 범위(전체 Mods / 지정 하위 폴더 / 개별 지정 폴더) UI 동기화
  const applyFolderScopeUI = (modsFolder, scanSubfolder = '', scanTargetPath = '') => {
    const sub = String(scanSubfolder || '').trim();
    const modsClean = String(modsFolder || '').trim();
    const displayPath = sub
      ? String(scanTargetPath || `${modsClean}\\${sub}`).trim()
      : String(scanTargetPath || modsClean).trim();

    const modsLeaf = extractLeafName(modsClean);
    const targetLeaf = extractLeafName(displayPath);
    const isCustomNonModsRoot = Boolean(!sub && modsLeaf && modsLeaf.toLowerCase() !== 'mods');
    const isScoped = Boolean(sub || isCustomNonModsRoot);
    const fullLabel = sub || (isCustomNonModsRoot ? targetLeaf : '');
    const shortLabel = targetLeaf || fullLabel;
    const isWwAnimScope = isScoped && detectWwAnimPathHint(`${sub} ${targetLeaf}`);

    activeScopeState = {
      modsFolder: modsClean,
      scanSubfolder: sub,
      scanTargetPath: displayPath,
      isScoped,
      isWwAnimScope,
      shortLabel,
      fullLabel,
    };

    if (modFolderPath && displayPath) {
      modFolderPath.textContent = displayPath;
      modFolderPath.title = sub
        ? `지정 폴더 스캔 중: ${displayPath} (상위 Mods: ${modsClean})`
        : displayPath;
    }
    if (pathScopeBadge) {
      if (isWwAnimScope) {
        pathScopeBadge.textContent = '🎞️ WW 애니메이션 폴더';
      } else if (sub) {
        pathScopeBadge.textContent = '📂 하위 폴더';
      } else if (isCustomNonModsRoot) {
        pathScopeBadge.textContent = '📂 지정 폴더';
      } else {
        pathScopeBadge.textContent = '📂 모드 폴더';
      }
    }
    if (resetSubfolderBtn) {
      resetSubfolderBtn.classList.toggle('is-hidden', !sub);
    }
    if (totalMoodletLabelEl) {
      totalMoodletLabelEl.textContent = isWwAnimScope
        ? '폴더 내 애니메이션'
        : isScoped
        ? '지정 폴더 항목'
        : '전체 설치 모드';
    }
    updateDashboard();
  };

  // 작업 진행 중 중복 클릭 방지 (스캔 중에도 폴더/하위 폴더 변경은 즉시 허용하여 전체 스캔을 중단하고 전환 가능)
  const applyBusyLockState = () => {
    const isUpdateBusy = isBusy && busyMode === 'update';
    if (backupBtn) backupBtn.disabled = isBusy;
    if (refreshBtn) refreshBtn.disabled = isBusy;
    if (selectSubfolderBtn) selectSubfolderBtn.disabled = isUpdateBusy;
    if (resetSubfolderBtn) resetSubfolderBtn.disabled = isUpdateBusy;
    if (changeFolderBtn) changeFolderBtn.disabled = isUpdateBusy;
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
      modList.querySelectorAll('.mod-variant-select').forEach((sel) => {
        sel.disabled = isBusy;
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
      category = getScanQuoteCategory(),
      doneQuote = getNextCompleteQuote(),
      tone = 'complete',
      mode = category === 'update' ? 'update' : 'scan',
    } = options;

    isBusy = isLoading;
    busyMode = isLoading ? mode : '';

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
    if (currentFilter === 'conflict' && mod.statusType !== 'conflict') {
      return false;
    }
    if (currentFilter === 'error' && mod.statusType !== 'error') {
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
      const wwAnimMatch =
        Boolean(mod.isWwAnimation) &&
        ('ww 애니메이션'.includes(q) || 'wickedwhims'.includes(q));
      return nameMatch || authorMatch || versionMatch || wwAnimMatch;
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
    const conflictCount = currentMods.filter((m) => m.statusType === 'conflict').length;
    const errorCount = currentMods.filter((m) => m.statusType === 'error').length;
    const latestCount = currentMods.filter((m) => m.statusType === 'latest').length;

    if (countTotalEl) countTotalEl.textContent = String(totalCount);
    if (countUpdateEl) countUpdateEl.textContent = String(updateCount);
    if (countConflictEl) countConflictEl.textContent = String(conflictCount);
    if (countErrorEl) countErrorEl.textContent = String(errorCount);
    if (countLatestEl) countLatestEl.textContent = String(latestCount);

    if (modListLabel) {
      const scopePrefix = activeScopeState.isScoped && activeScopeState.shortLabel
        ? `[${activeScopeState.shortLabel}] `
        : '';
      modListLabel.textContent = `${scopePrefix}업데이트 대상 목록 (총 ${totalCount}개 / 업데이트 가능 ${updateCount}개)`;
    }

    if (moodletGrid) {
      moodletGrid.querySelectorAll('.moodlet-card').forEach((card) => {
        card.classList.toggle('is-active', card.dataset.filter === currentFilter);
      });
    }
  };

  // 텍스트 클립보드 복사 유틸리티 (웹뷰 권한 제한 환경 폴백 포함)
  const copyTextToClipboard = async (text) => {
    const val = String(text || '');
    if (!val) return false;
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(val);
        return true;
      }
    } catch (_) {
      // fallback below
    }
    try {
      const ta = document.createElement('textarea');
      ta.value = val;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      ta.style.top = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return Boolean(ok);
    } catch (_) {
      return false;
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
        const scopeTag = activeScopeState.isScoped && activeScopeState.shortLabel
          ? `[${activeScopeState.shortLabel}] 지정 폴더`
          : '모드 폴더';
        emptyEl.textContent = isInitializing
          ? `${scopeTag}에서 항목을 불러오는 중입니다...`
          : activeScopeState.isScoped
          ? `${scopeTag}에 설치된 스크립트/게임플레이 모드 및 WW 애니메이션이 없습니다.`
          : '선택된 Mods 폴더에 설치된 스크립트/게임플레이 모드가 없습니다.';
      } else if (searchQuery.trim() !== '') {
        emptyEl.textContent = `"${searchQuery.trim()}" 검색 결과가 없습니다.`;
      } else {
        emptyEl.textContent = '해당 무드렛 상태의 모드가 없습니다.';
      }
      modList.appendChild(emptyEl);
      syncSelectionState();
      requestAnimationFrame(updateScrollArrows);
      return;
    }

    const fragment = document.createDocumentFragment();
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

      const nameEl = document.createElement('span');
      nameEl.className = 'mod-name';
      nameEl.textContent = mod.name;
      nameEl.title = mod.name;

      titleRowEl.appendChild(nameEl);

      if (mod.isWwAnimation) {
        const wwAnimBadgeEl = document.createElement('span');
        wwAnimBadgeEl.className = 'mod-ww-anim-badge';
        wwAnimBadgeEl.textContent = 'WW 애니메이션';
        wwAnimBadgeEl.title = 'WickedWhims 애니메이션 팩';
        titleRowEl.appendChild(wwAnimBadgeEl);
      }

      let filenameRowEl = null;
      if (mod.primaryFile) {
        filenameRowEl = document.createElement('div');
        filenameRowEl.className = 'mod-filename-row';

        const filenameEl = document.createElement('span');
        filenameEl.className = 'mod-filename';
        filenameEl.textContent = mod.primaryFile;
        filenameEl.title = mod.primaryFile;

        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'btn-copy-filename';
        copyBtn.title = '파일명 클립보드 복사';
        copyBtn.textContent = '📋';
        copyBtn.addEventListener('click', async (event) => {
          event.stopPropagation();
          const copied = await copyTextToClipboard(mod.primaryFile);
          if (copied) {
            copyBtn.textContent = '✓ 복사됨';
            copyBtn.classList.add('is-copied');
            setLog(`파일명이 클립보드에 복사되었습니다: ${mod.primaryFile}`);
            setTimeout(() => {
              copyBtn.textContent = '📋';
              copyBtn.classList.remove('is-copied');
            }, 1200);
          } else {
            setLog(`드래그 후 Ctrl+C로 복사해 주세요: ${mod.primaryFile}`);
          }
        });

        filenameRowEl.appendChild(filenameEl);
        filenameRowEl.appendChild(copyBtn);
      }

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

      if (mod.optionModalMode === 'multi_file_select') {
        const isAllDl = (mod.selectedVariant || 'download_mode:all') === 'download_mode:all';
        const selCnt = Array.isArray(mod.selectedAddons) ? mod.selectedAddons.length : 0;
        const dlModeBtn = document.createElement('button');
        dlModeBtn.type = 'button';
        dlModeBtn.className = 'mod-channel-pill is-free';
        dlModeBtn.disabled = isBusy;
        dlModeBtn.textContent = isAllDl
          ? '전체 다운로드 ▾'
          : `선택 다운로드 (${selCnt}개) ▾`;
        dlModeBtn.title = '전체 다운로드 / 선택 다운로드(다중 선택) 설정';
        dlModeBtn.addEventListener('click', async (event) => {
          event.stopPropagation();
          if (isBusy) return;
          const modalResult = await openOptionSelectModal(mod, {
            confirmLabel: '옵션 저장',
          });
          if (!modalResult || !modalResult.selectedVariant) {
            setLog(`[${mod.name}] 다운로드 옵션 선택이 취소되었습니다.`);
            return;
          }
          mod.selectedVariant = modalResult.selectedVariant;
          mod.selectedAddons = Array.isArray(modalResult.selectedAddons)
            ? modalResult.selectedAddons
            : [];
          if (hasPywebview() && window.pywebview.api.set_mod_variant) {
            try {
              const varRes = await window.pywebview.api.set_mod_variant(
                mod.id,
                modalResult.selectedVariant,
                mod.selectedAddons
              );
              if (varRes?.error) {
                setLog(`옵션 변경 오류: ${varRes.error}`);
                return;
              }
              if (varRes?.entry) {
                Object.assign(mod, varRes.entry);
                renderModList(currentMods);
              }
              if (varRes?.message) {
                setLog(varRes.message);
              }
            } catch (err) {
              setLog(`옵션 변경 오류: ${err}`);
            }
          } else {
            renderModList(currentMods);
          }
        });
        metaRowEl.appendChild(dlModeBtn);
      }

      if (mod.optionModalMode === 'rpo_channel' || mod.optionModalMode === 'ww_channel') {
        const isWwChannel = mod.optionModalMode === 'ww_channel';
        const isFreeChannel = isWwChannel ? mod.wwChannel !== 'paid' : mod.rpoChannel === 'free';
        const channelBtn = document.createElement('button');
        channelBtn.type = 'button';
        channelBtn.className = `mod-channel-pill ${isFreeChannel ? 'is-free' : 'is-early'}`;
        channelBtn.disabled = isBusy;
        channelBtn.textContent = isFreeChannel
          ? '무료 버전 ▾'
          : '선배포 버전 ▾';
        channelBtn.title = isWwChannel
          ? 'WickedWhims 무료 버전(v185k) / 선배포 버전(v187.18) 전환'
          : 'RPO Collection 선배포 버전 / 무료 버전 전환';
        channelBtn.addEventListener('click', async (event) => {
          event.stopPropagation();
          if (isBusy) return;
          const modalResult = await openOptionSelectModal(mod, {
            confirmLabel: '옵션 저장 및 적용',
          });
          if (!modalResult || !modalResult.selectedVariant) {
            setLog(`[${mod.name}] 버전 선택이 취소되었습니다.`);
            return;
          }
          if (hasPywebview() && window.pywebview.api.set_mod_variant) {
            try {
              const varRes = await window.pywebview.api.set_mod_variant(
                mod.id,
                modalResult.selectedVariant,
                null
              );
              if (varRes?.error) {
                setLog(`옵션 변경 오류: ${varRes.error}`);
                return;
              }
              if (Array.isArray(varRes?.mods)) {
                renderModList(varRes.mods);
              } else if (varRes?.entry) {
                Object.assign(mod, varRes.entry);
                renderModList(currentMods);
              }
              if (varRes?.message) {
                setLog(varRes.message);
              }
            } catch (err) {
              setLog(`옵션 변경 오류: ${err}`);
            }
          }
        });
        metaRowEl.appendChild(channelBtn);
      }

      infoEl.appendChild(titleRowEl);
      if (filenameRowEl) {
        infoEl.appendChild(filenameRowEl);
      }
      infoEl.appendChild(metaRowEl);

      // 택1 옵션(예: Canvas Frame Override v1~v3 등)이 있는 모드는 카드 하단에 콤팩트 선택 드롭다운 표시
      // (requiresOptionModal이 활성화된 모드는 업데이트 시 전용 선택 모달을 띄우므로 카드 레이아웃을 유지)
      if (!mod.requiresOptionModal && Array.isArray(mod.variantChoices) && mod.variantChoices.length > 1) {
        const variantRowEl = document.createElement('div');
        variantRowEl.className = 'mod-variant-row';

        const variantBadgeEl = document.createElement('span');
        variantBadgeEl.className = 'mod-variant-badge';
        variantBadgeEl.textContent = '옵션 택1';

        const variantSelectEl = document.createElement('select');
        variantSelectEl.className = 'mod-variant-select';
        variantSelectEl.disabled = isBusy;
        variantSelectEl.setAttribute('aria-label', `${mod.name} 설치 옵션 선택`);
        variantSelectEl.title = '동시 설치 불가 옵션 — 1개만 선택해 다운로드합니다';

        mod.variantChoices.forEach((vc) => {
          const opt = document.createElement('option');
          opt.value = vc.file_name;
          opt.textContent = vc.label || vc.file_name;
          if ((mod.selectedVariant || mod.variantChoices[0].file_name) === vc.file_name) {
            opt.selected = true;
          }
          variantSelectEl.appendChild(opt);
        });

        variantSelectEl.addEventListener('change', async (event) => {
          const nextVariant = event.target.value;
          mod.selectedVariant = nextVariant;
          if (hasPywebview() && window.pywebview.api.set_mod_variant) {
            try {
              const res = await window.pywebview.api.set_mod_variant(mod.id, nextVariant);
              if (res?.ok && res?.entry) {
                Object.assign(mod, res.entry);
                renderModList(currentMods);
              }
              if (res?.message) {
                setLog(res.message);
              }
            } catch (err) {
              setLog(`옵션 선택 반영 오류: ${err}`);
            }
          } else {
            setLog(`[${mod.name}] 설치 옵션 선택: ${nextVariant}`);
          }
        });

        variantRowEl.appendChild(variantBadgeEl);
        variantRowEl.appendChild(variantSelectEl);
        infoEl.appendChild(variantRowEl);
      }

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

      fragment.appendChild(cardEl);
    });

    modList.appendChild(fragment);
    syncSelectionState();
    requestAnimationFrame(updateScrollArrows);
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
    const autoLaunch = autoLaunchCheckbox ? autoLaunchCheckbox.checked : false;

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
      if (nextFilter === 'conflict') {
        const hasConflict = currentMods.some((m) => m.statusType === 'conflict');
        if (hasConflict) setWittyQuote(SIMS4_QUOTES.error[0], 'error');
      } else if (nextFilter === 'error') {
        const hasError = currentMods.some((m) => m.statusType === 'error');
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

  // 백엔드 원격 병렬 스캔 실행 함수 (force=true 시 진행 중이던 이전 스캔을 대체하여 즉시 재실행)
  const runRemoteScan = async ({ force = false, scanToken = null } = {}) => {
    if (!hasPywebview()) return;
    if (isBusy && (!force || busyMode === 'update')) return;

    const myToken = scanToken !== null ? scanToken : ++activeScanToken;
    const scopeName = activeScopeState.isScoped
      ? activeScopeState.shortLabel || activeScopeState.fullLabel
      : '';
    setLoading(true, getScopeLoadingMessage('remote'), {
      category: getScanQuoteCategory(),
      mode: 'scan',
    });
    if (statusSummary) {
      statusSummary.textContent = scopeName
        ? `진행 상태: [${scopeName}] 스캔 준비 중...`
        : '진행 상태: 원격 스캔 준비 중...';
    }
    if (progressBar) progressBar.style.width = '8%';

    try {
      const res = await window.pywebview.api.scan_mods(true);
      if (myToken !== activeScanToken || res?.superseded) {
        return;
      }
      if (res?.error) {
        setLog(`스캔 오류: ${res.error}`);
        setLoading(false, '', {
          doneQuote: SIMS4_QUOTES.error[0],
          tone: 'error',
        });
        return;
      }
      if (res?.mods_folder || res?.scan_target_path) {
        applyFolderScopeUI(
          res?.mods_folder || '',
          res?.scan_subfolder || '',
          res?.scan_target_path || ''
        );
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
      if (myToken !== activeScanToken) return;
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

  // 옵션 선택 모달 (More Columns in CAS, First Impressions, RPO Collection 등 옵션 선택용)
  const openOptionSelectModal = (mod, modalOpts = {}) => {
    const choices = Array.isArray(mod?.variantChoices) ? mod.variantChoices : [];
    const addons = Array.isArray(mod?.optionalAddons) ? mod.optionalAddons : [];
    if (!optionSelectModal || !optionModalList || (choices.length === 0 && addons.length === 0)) {
      return Promise.resolve({
        selectedVariant: mod?.selectedVariant || choices[0]?.file_name || '',
        selectedAddons: Array.isArray(mod?.selectedAddons) ? mod.selectedAddons : [],
      });
    }

    const isChannelMode = mod?.optionModalMode === 'rpo_channel' || mod?.optionModalMode === 'ww_channel';
    const isMultiFileSelectMode = mod?.optionModalMode === 'multi_file_select';
    const primaryLow = String(mod.primaryFile || '').trim().toLowerCase();
    const initialChoice =
      choices.find((vc) => vc.file_name === mod.selectedVariant) ||
      choices.find((vc) => vc.installed || vc.file_name.toLowerCase() === primaryLow) ||
      choices[0];
    let selectedFile = initialChoice ? initialChoice.file_name : '';

    const selectedAddonsLow = new Set(
      (Array.isArray(mod.selectedAddons) && mod.selectedAddons.length > 0
        ? mod.selectedAddons
        : addons.filter((oa) => oa.installed).map((oa) => oa.file_name)
      ).map((fn) => String(fn).toLowerCase())
    );
    if (isMultiFileSelectMode && selectedAddonsLow.size === 0) {
      addons.forEach((oa) => selectedAddonsLow.add(String(oa.file_name || '').toLowerCase()));
    }

    if (optionModalTitle) {
      optionModalTitle.textContent = mod.name || '모드 옵션 선택';
    }
    if (optionModalDesc) {
      optionModalDesc.textContent =
        mod.optionModalPrompt ||
        '설치할 버전을 선택해 주세요. (동시 설치 불가 · 1개 선택)';
    }
    if (optionModalConfirmBtn) {
      optionModalConfirmBtn.textContent = modalOpts.confirmLabel || '선택 완료 및 업데이트';
    }

    let addonContainerEl = null;
    const syncSelectedVisuals = () => {
      const radioItems = optionModalList.querySelectorAll('.option-modal-item[role="radio"]');
      radioItems.forEach((btn) => {
        const isSel = btn.dataset.fileName === selectedFile;
        btn.classList.toggle('is-selected', isSel);
        btn.setAttribute('aria-checked', isSel ? 'true' : 'false');
      });
      if (isMultiFileSelectMode && addonContainerEl) {
        addonContainerEl.classList.toggle('is-hidden', selectedFile !== 'download_mode:select');
      }
      const checkItems = optionModalList.querySelectorAll('.option-modal-item[role="checkbox"]');
      checkItems.forEach((btn) => {
        const isChk = selectedAddonsLow.has(String(btn.dataset.fileName || '').toLowerCase());
        btn.classList.toggle('is-selected', isChk);
        btn.setAttribute('aria-checked', isChk ? 'true' : 'false');
      });
    };

    optionModalList.innerHTML = '';

    if (addons.length > 0 && choices.length > 0) {
      const mainSectionEl = document.createElement('div');
      mainSectionEl.className = 'option-section-label';
      mainSectionEl.textContent = isMultiFileSelectMode ? '다운로드 방식 (택1)' : '필수 본체 버전 (택1)';
      optionModalList.appendChild(mainSectionEl);
    }

    choices.forEach((vc) => {
      const itemBtn = document.createElement('button');
      itemBtn.type = 'button';
      itemBtn.className = 'option-modal-item';
      itemBtn.setAttribute('role', 'radio');
      itemBtn.dataset.fileName = vc.file_name;

      const dotEl = document.createElement('span');
      dotEl.className = 'option-radio-dot';
      dotEl.setAttribute('aria-hidden', 'true');

      const textWrapEl = document.createElement('div');
      textWrapEl.className = 'option-item-text';

      const labelRowEl = document.createElement('div');
      labelRowEl.className = 'option-item-label-row';

      const labelEl = document.createElement('span');
      labelEl.className = 'option-item-label';
      labelEl.textContent = vc.label || vc.file_name;
      labelRowEl.appendChild(labelEl);

      if (
        !isMultiFileSelectMode &&
        (vc.installed || (!isChannelMode && primaryLow && vc.file_name.toLowerCase() === primaryLow))
      ) {
        const curBadgeEl = document.createElement('span');
        curBadgeEl.className = 'option-current-badge';
        curBadgeEl.textContent = isChannelMode ? '현재 선택됨' : '현재 설치됨';
        labelRowEl.appendChild(curBadgeEl);
      }

      const fileNameEl = document.createElement('span');
      fileNameEl.className = 'option-item-filename';
      fileNameEl.textContent = vc.description || vc.file_name;

      textWrapEl.appendChild(labelRowEl);
      textWrapEl.appendChild(fileNameEl);

      itemBtn.appendChild(dotEl);
      itemBtn.appendChild(textWrapEl);
      itemBtn.addEventListener('click', () => {
        selectedFile = vc.file_name;
        syncSelectedVisuals();
      });

      optionModalList.appendChild(itemBtn);
    });

    if (addons.length > 0) {
      addonContainerEl = document.createElement('div');
      addonContainerEl.className = 'option-addon-group';
      addonContainerEl.style.display = 'flex';
      addonContainerEl.style.flexDirection = 'column';
      addonContainerEl.style.gap = '8px';

      const addonSectionEl = document.createElement('div');
      addonSectionEl.className = 'option-section-label';
      addonSectionEl.textContent = isMultiFileSelectMode
        ? '다운로드할 파일 선택 (다중 선택 가능)'
        : '세부 옵션 파일 (선택 사항 · 복수 선택 가능)';
      addonContainerEl.appendChild(addonSectionEl);

      addons.forEach((oa) => {
        const itemBtn = document.createElement('button');
        itemBtn.type = 'button';
        itemBtn.className = 'option-modal-item';
        itemBtn.setAttribute('role', 'checkbox');
        itemBtn.dataset.fileName = oa.file_name;

        const boxEl = document.createElement('span');
        boxEl.className = 'option-check-box';
        boxEl.setAttribute('aria-hidden', 'true');
        boxEl.textContent = '✓';

        const textWrapEl = document.createElement('div');
        textWrapEl.className = 'option-item-text';

        const labelRowEl = document.createElement('div');
        labelRowEl.className = 'option-item-label-row';

        const labelEl = document.createElement('span');
        labelEl.className = 'option-item-label';
        labelEl.textContent = oa.label || oa.file_name;
        labelRowEl.appendChild(labelEl);

        if (oa.installed) {
          const curBadgeEl = document.createElement('span');
          curBadgeEl.className = 'option-current-badge';
          curBadgeEl.textContent = '현재 설치됨';
          labelRowEl.appendChild(curBadgeEl);
        }

        const fileNameEl = document.createElement('span');
        fileNameEl.className = 'option-item-filename';
        fileNameEl.textContent = oa.file_name;

        textWrapEl.appendChild(labelRowEl);
        textWrapEl.appendChild(fileNameEl);

        itemBtn.appendChild(boxEl);
        itemBtn.appendChild(textWrapEl);
        itemBtn.addEventListener('click', () => {
          const low = oa.file_name.toLowerCase();
          if (selectedAddonsLow.has(low)) {
            selectedAddonsLow.delete(low);
          } else {
            selectedAddonsLow.add(low);
          }
          syncSelectedVisuals();
        });

        addonContainerEl.appendChild(itemBtn);
      });

      optionModalList.appendChild(addonContainerEl);
    }

    syncSelectedVisuals();
    optionSelectModal.classList.remove('is-hidden');

    return new Promise((resolve) => {
      let settled = false;
      const cleanupAndResolve = (result) => {
        if (settled) return;
        settled = true;
        optionSelectModal.classList.add('is-hidden');
        optionModalConfirmBtn?.removeEventListener('click', onConfirm);
        optionModalCancelBtn?.removeEventListener('click', onCancel);
        optionModalCloseBtn?.removeEventListener('click', onCancel);
        optionSelectModal.removeEventListener('click', onBackdropClick);
        document.removeEventListener('keydown', onKeyDown);
        resolve(result);
      };

      const onConfirm = () => {
        const chosenAddons = addons
          .filter((oa) => selectedAddonsLow.has(oa.file_name.toLowerCase()))
          .map((oa) => oa.file_name);
        if (isMultiFileSelectMode && selectedFile === 'download_mode:select' && chosenAddons.length === 0) {
          setLog(`[${mod.name}] 선택 다운로드 시 최소 1개 이상의 파일을 선택해 주세요.`);
          return;
        }
        cleanupAndResolve({
          selectedVariant: selectedFile || choices[0]?.file_name || '',
          selectedAddons:
            isMultiFileSelectMode && selectedFile === 'download_mode:all'
              ? addons.map((oa) => oa.file_name)
              : chosenAddons,
        });
      };
      const onCancel = () => cleanupAndResolve(null);
      const onBackdropClick = (ev) => {
        if (ev.target === optionSelectModal) onCancel();
      };
      const onKeyDown = (ev) => {
        if (ev.key === 'Escape') {
          ev.preventDefault();
          onCancel();
        } else if (ev.key === 'Enter') {
          ev.preventDefault();
          onConfirm();
        }
      };

      optionModalConfirmBtn?.addEventListener('click', onConfirm);
      optionModalCancelBtn?.addEventListener('click', onCancel);
      optionModalCloseBtn?.addEventListener('click', onCancel);
      optionSelectModal.addEventListener('click', onBackdropClick);
      document.addEventListener('keydown', onKeyDown);
      optionModalConfirmBtn?.focus();
    });
  };

  // 모드 업데이트 실행 및 선택적 심즈4 런치
  const executeModUpdates = async (targetIds, launchGameAfter = false) => {
    if (isBusy || !targetIds || targetIds.length === 0) return;

    const effectiveTargetIds = [];
    // 옵션 선택 모달이 필요한 모드(예: More Columns in CAS, First Impressions, RPO Collection 등)가 포함된 경우 업데이트 전에 사용자 선택 확인
    for (const modId of targetIds) {
      const targetMod = currentMods.find((m) => m.id === modId);
      if (
        targetMod &&
        targetMod.requiresOptionModal &&
        Array.isArray(targetMod.variantChoices) &&
        targetMod.variantChoices.length > 0
      ) {
        const isRpoChannelMode = targetMod.optionModalMode === 'rpo_channel';
        const isWwChannelMode = targetMod.optionModalMode === 'ww_channel';
        const modalResult = await openOptionSelectModal(targetMod);
        if (!modalResult || !modalResult.selectedVariant) {
          setLog(`[${targetMod.name}] 옵션 선택이 취소되어 업데이트를 중단했습니다.`);
          return;
        }
        const chosenVariant = modalResult.selectedVariant;
        const hasOptionalAddons =
          Array.isArray(targetMod.optionalAddons) && targetMod.optionalAddons.length > 0;
        const chosenAddons = hasOptionalAddons
          ? Array.isArray(modalResult.selectedAddons)
            ? modalResult.selectedAddons
            : []
          : null;
        targetMod.selectedVariant = chosenVariant;
        if (hasOptionalAddons) {
          targetMod.selectedAddons = chosenAddons;
        }
        if (hasPywebview() && window.pywebview.api.set_mod_variant) {
          try {
            const varRes = await window.pywebview.api.set_mod_variant(
              targetMod.id,
              chosenVariant,
              chosenAddons
            );
            if (varRes?.error) {
              setLog(`옵션 선택 반영 오류: ${varRes.error}`);
              return;
            }
            if (Array.isArray(varRes?.mods)) {
              currentMods = varRes.mods;
              Object.assign(targetMod, currentMods.find((m) => m.id === targetMod.id) || {});
            } else if (varRes?.entry) {
              Object.assign(targetMod, varRes.entry);
            }
            if (varRes?.message) {
              setLog(varRes.message);
            }
          } catch (err) {
            setLog(`옵션 선택 반영 오류: ${err}`);
            return;
          }
        }
        if (
          (isRpoChannelMode && chosenVariant === 'rpo_channel:early_access') ||
          (isWwChannelMode && chosenVariant === 'ww_channel:paid')
        ) {
          renderModList(currentMods);
          setLog(
            `[${targetMod.name}] 선배포 버전을 선택하여 자동 다운로드를 실행하지 않고 '수동 확인' 상태를 유지합니다.`
          );
          continue;
        }
      }
      effectiveTargetIds.push(modId);
    }

    if (effectiveTargetIds.length === 0) {
      if (launchGameAfter) {
        await launchSims4Directly();
      }
      return;
    }

    setLoading(true, '플럼밥이 업데이트 중...', { category: 'update' });
    if (progressBar) progressBar.style.width = '5%';

    if (hasPywebview()) {
      try {
        const res = await window.pywebview.api.update_selected_mods(
          effectiveTargetIds,
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
          statusSummary.textContent = `진행 상태: 완료 (${effectiveTargetIds.length} / ${effectiveTargetIds.length})`;
        }
        setLog(
          res?.message ||
            `선택한 ${effectiveTargetIds.length}개 모드 업데이트가 완료되었습니다!`
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
      const total = effectiveTargetIds.length;
      for (const id of effectiveTargetIds) {
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
        setLoading(true, getScopeLoadingMessage('remote'), {
          category: getScanQuoteCategory(),
          mode: 'scan',
        });
        setLog(
          activeScopeState.isScoped
            ? `[${activeScopeState.shortLabel}] 지정 폴더 및 원격 버전을 확인하고 있습니다...`
            : '모드 폴더 및 원격 버전을 확인하고 있습니다...'
        );
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

  // 하위 폴더 지정 스캔 버튼
  if (selectSubfolderBtn) {
    selectSubfolderBtn.addEventListener('click', async () => {
      if (isBusy && busyMode === 'update') return;
      if (hasPywebview()) {
        try {
          const res = await window.pywebview.api.select_scan_subfolder();
          if (res?.cancelled) return;
          const nextToken = ++activeScanToken;
          if (res?.error) {
            setLog(`하위 폴더 지정 오류: ${res.error}`);
            setLoading(false, '', { doneQuote: SIMS4_QUOTES.error[0], tone: 'error' });
            return;
          }
          applyFolderScopeUI(
            res?.mods_folder || '',
            res?.scan_subfolder || '',
            res?.scan_target_path || ''
          );
          if (Array.isArray(res?.mods)) {
            isInitializing = false;
            currentFilter = 'all';
            renderModList(res.mods);
          }
          setLog(res?.message || '스캔 대상 하위 폴더가 지정되었습니다.');
          if (res?.needs_remote_scan) {
            await runRemoteScan({ force: true, scanToken: nextToken });
          } else {
            if (progressBar) progressBar.style.width = res?.cached ? '100%' : '0%';
            setLoading(false, '', { doneQuote: getNextCompleteQuote(), tone: 'complete' });
          }
        } catch (err) {
          setLog(`하위 폴더 지정 중 오류가 발생했습니다: ${err}`);
          setLoading(false, '', { doneQuote: SIMS4_QUOTES.error[0], tone: 'error' });
        }
      } else {
        const subInput = window.prompt('Mods 기준 스캔할 하위 폴더 상대 경로를 입력하세요 (비우면 전체):', '');
        if (subInput !== null) {
          const clean = subInput.trim();
          applyFolderScopeUI('Mods', clean, clean ? `Mods\\${clean}` : 'Mods');
          setLog(clean ? `[${clean}] 하위 폴더 지정됨` : '전체 Mods 폴더로 복귀했습니다.');
        }
      }
    });
  }

  // 전체 Mods 폴더 스캔 복귀 버튼
  if (resetSubfolderBtn) {
    resetSubfolderBtn.addEventListener('click', async () => {
      if (isBusy && busyMode === 'update') return;
      if (hasPywebview()) {
        try {
          const nextToken = ++activeScanToken;
          const res = await window.pywebview.api.set_scan_subfolder('');
          if (res?.error) {
            setLog(`전체 보기 전환 오류: ${res.error}`);
            setLoading(false, '', { doneQuote: SIMS4_QUOTES.error[0], tone: 'error' });
            return;
          }
          applyFolderScopeUI(
            res?.mods_folder || '',
            res?.scan_subfolder || '',
            res?.scan_target_path || ''
          );
          if (Array.isArray(res?.mods)) {
            isInitializing = false;
            currentFilter = 'all';
            renderModList(res.mods);
          }
          setLog(res?.message || '전체 Mods 폴더 스캔으로 복귀했습니다.');
          if (res?.needs_remote_scan) {
            await runRemoteScan({ force: true, scanToken: nextToken });
          } else {
            if (progressBar) progressBar.style.width = res?.cached ? '100%' : '0%';
            setLoading(false, '', { doneQuote: getNextCompleteQuote(), tone: 'complete' });
          }
        } catch (err) {
          setLog(`전체 보기 전환 중 오류가 발생했습니다: ${err}`);
          setLoading(false, '', { doneQuote: SIMS4_QUOTES.error[0], tone: 'error' });
        }
      } else {
        applyFolderScopeUI('Mods', '', 'Mods');
        setLog('전체 Mods 폴더 스캔으로 복귀했습니다.');
      }
    });
  }

  // 폴더 변경 버튼
  if (changeFolderBtn) {
    changeFolderBtn.addEventListener('click', async () => {
      if (isBusy && busyMode === 'update') return;
      if (hasPywebview()) {
        try {
          const res = await window.pywebview.api.select_mods_folder();
          if (res?.cancelled) return;
          const nextToken = ++activeScanToken;
          if (res?.error) {
            setLog(`폴더 변경 오류: ${res.error}`);
            setLoading(false, '', { doneQuote: SIMS4_QUOTES.error[0], tone: 'error' });
            return;
          }
          if (res?.mods_folder || res?.scan_target_path) {
            applyFolderScopeUI(
              res?.mods_folder || '',
              res?.scan_subfolder || '',
              res?.scan_target_path || ''
            );
          }
          if (Array.isArray(res?.mods)) {
            isInitializing = false;
            currentFilter = 'all';
            renderModList(res.mods);
          }
          setLog(res?.message || '폴더 경로가 변경되었습니다.');
          if (res?.needs_remote_scan) {
            await runRemoteScan({ force: true, scanToken: nextToken });
          } else {
            if (progressBar) progressBar.style.width = res?.cached ? '100%' : '0%';
            setLoading(false, '', { doneQuote: getNextCompleteQuote(), tone: 'complete' });
          }
        } catch (err) {
          setLog(`폴더 변경 중 오류가 발생했습니다: ${err}`);
          setLoading(false, '', { doneQuote: SIMS4_QUOTES.error[0], tone: 'error' });
        }
      } else {
        const currentPath = modFolderPath ? modFolderPath.textContent.trim() : '';
        const nextPath = window.prompt('변경할 폴더 경로를 입력하세요:', currentPath);
        if (nextPath && nextPath.trim() && modFolderPath) {
          applyFolderScopeUI(nextPath.trim(), '', nextPath.trim());
          setLog(`폴더 경로가 변경되었습니다: ${nextPath.trim()}`);
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

      const launchAfter = autoLaunchCheckbox ? autoLaunchCheckbox.checked : false;
      await executeModUpdates(selectedIds, launchAfter);
    });
  }

  // 초기 화면 렌더링 (하드코딩된 예시 데이터 없이 빈 로딩 상태로 시작 후 pywebview 준비 시 실제 로컬 폴더 반영)
  renderModList(currentMods);

  // pywebview 환경 준비 시 2단계 비차단 스캔 (1단계: 로컬 0.5초 즉시 표시 -> 2단계: 백그라운드 병렬 원격 조회)
  window.addEventListener('pywebviewready', async () => {
    if (!hasPywebview()) return;
    const initToken = ++activeScanToken;
    try {
      const state = await window.pywebview.api.get_initial_state();
      if (initToken !== activeScanToken) {
        return;
      }
      isInitializing = false;
      if (state?.mods_folder || state?.scan_target_path) {
        applyFolderScopeUI(
          state?.mods_folder || '',
          state?.scan_subfolder || '',
          state?.scan_target_path || ''
        );
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
        await runRemoteScan({ force: true, scanToken: initToken });
      }
    } catch (_) {
      if (initToken !== activeScanToken) return;
      isInitializing = false;
      renderModList([]);
      setWittyQuote(SIMS4_QUOTES.error[0], 'error');
    }
  });

  const onBackendProgress = (payload) => {
    if (!payload) return;
    const rawScope = String(payload.scopeLabel || '').trim();
    // 이미 특정 폴더 스캔으로 전환되었는데 이전 전체 Mods 스캔의 지연된 이벤트가 도착한 경우 무시
    if (payload.mode === 'scan' && activeScopeState.isScoped && !rawScope) {
      return;
    }
    if (typeof payload.percent === 'number' && progressBar) {
      progressBar.style.width = `${payload.percent}%`;
    }
    if (
      typeof payload.completed === 'number' &&
      typeof payload.total === 'number' &&
      statusSummary
    ) {
      const shortScope = rawScope
        ? extractLeafName(rawScope) || rawScope
        : activeScopeState.isScoped
        ? activeScopeState.shortLabel
        : '';
      const actionLabel =
        payload.mode === 'scan'
          ? shortScope
            ? `[${shortScope}] 스캔 중`
            : '원격 스캔 중'
          : '업데이트 중';
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
    pathScopeBadge,
    selectSubfolderBtn,
    resetSubfolderBtn,
    changeFolderBtn,
    applyFolderScopeUI,
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
