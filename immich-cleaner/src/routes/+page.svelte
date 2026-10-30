<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import { formatScore } from '#lib/score';

  type CleanerAsset = {
    id: string;
    score: number;
    originalFileName: string | null;
    originalPath: string | null;
    thumbnailUrl: string;
    originalUrl: string;
    isExcluded: boolean;
    exclusionReason: 'manual' | 'rescued' | null;
  };

  type SearchPage = {
    query: string;
    page: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
    includeExcluded: boolean;
    searchSize: number;
    items: CleanerAsset[];
  };

  type PublicConfig = {
    configured: boolean;
    presets: string[];
    defaultSearchSize: number;
    trashMethod: string;
  };

  type OriginalImageState =
    | {
        status: 'loading';
        promise: Promise<void>;
        abort: AbortController;
      }
    | {
        status: 'loaded';
        url: string;
      }
    | {
        status: 'error';
        message: string;
      };

  type ViewTransitionHandle = {
    finished: Promise<void>;
    skipTransition: () => void;
  };

  type ViewTransitionDocument = Document & {
    startViewTransition?: (updateCallback: () => void | Promise<void>) => ViewTransitionHandle;
  };

  const now = new Date();
  const defaultYear = String(now.getFullYear());
  const defaultMonth = String(now.getMonth() === 0 ? 12 : now.getMonth());
  const yearOptions = Array.from({ length: now.getFullYear() - 1899 }, (_, index) =>
    String(now.getFullYear() - index)
  );
  const monthOptions = Array.from({ length: 12 }, (_, index) => String(index + 1));

  let presets: string[] = [];
  let configured = true;
  let query = '';
  let customQuery = '';
  let pageInput = '1';
  let pageSize = 100;
  let threshold: string | number | undefined = undefined;
  let includeExcluded = false;
  let selectedYear = defaultYear;
  let selectedMonth = defaultMonth;
  let searchSize = 1000;
  let result: SearchPage | null = null;
  let loading = false;
  let trashing = false;
  let configLoadFailed = false;
  let errorMessage = '';
  let noticeMessage = '';
  let selectedAssetIds = new Set<string>();
  let thresholdValue: number | null = null;
  let previewAsset: CleanerAsset | null = null;
  let transitionAssetId: string | null = null;
  let originalImages = new Map<string, OriginalImageState>();
  let resultAssetIdsKey = '';
  let activePreviewTransition: ViewTransitionHandle | null = null;
  let previewTransitionToken: symbol | null = null;
  let contextMenu:
    | {
        visible: true;
        x: number;
        y: number;
        asset: CleanerAsset;
      }
    | {
        visible: false;
        x: 0;
        y: 0;
        asset: null;
      } = { visible: false, x: 0, y: 0, asset: null };

  $: currentPage = result?.page ?? 1;
  $: totalPages = result?.totalPages ?? 1;
  $: totalItems = result?.totalItems ?? 0;
  $: pageInput = String(currentPage);
  $: selectedCount = selectedAssetIds.size;
  $: thresholdValue = parseThresholdInput(threshold);
  $: {
    const nextAssetIdsKey = result?.items.map((asset) => asset.id).join('\u0000') ?? '';
    if (nextAssetIdsKey !== resultAssetIdsKey) {
      resultAssetIdsKey = nextAssetIdsKey;
      pruneOriginalImageStates(new Set(result?.items.map((asset) => asset.id) ?? []));
    }
  }

  onMount(async () => {
    try {
      configLoadFailed = false;
      const config = await requestJson<PublicConfig>('/api/config');
      if (!config.presets.length) {
        throw new Error('DEFAULT_KEYWORD_PRESETS を取得できませんでした');
      }
      presets = config.presets;
      query = presets[0];
      searchSize = config.defaultSearchSize;
      configured = config.configured;
      if (configured) {
        await runSearch(query, 1);
      }
    } catch (error) {
      configLoadFailed = true;
      errorMessage = error instanceof Error ? error.message : '設定を読み込めませんでした';
    }
  });

  onDestroy(() => {
    for (const state of originalImages.values()) {
      releaseOriginalImageState(state);
    }
  });

  async function runSearch(nextQuery = query, nextPage = 1) {
    const normalizedQuery = nextQuery.trim();
    if (!normalizedQuery) {
      errorMessage = '検索キーワードを入力してください';
      return;
    }

    if (normalizedQuery !== query) {
      selectedAssetIds = new Set();
      threshold = undefined;
    }
    query = normalizedQuery;
    loading = true;
    errorMessage = '';
    noticeMessage = '';
    closeContextMenu();
    closeAssetPreview({ animated: false });

    try {
      result = await requestJson<SearchPage>('/api/search/smart', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          query: normalizedQuery,
          page: nextPage,
          pageSize,
          includeExcluded,
          size: searchSize,
          year: selectedYear || null,
          month: selectedYear && selectedMonth ? selectedMonth : null
        })
      });
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : '検索に失敗しました';
    } finally {
      loading = false;
    }
  }

  function selectPreset(preset: string) {
    customQuery = '';
    void runSearch(preset, 1);
  }

  function submitCustomQuery() {
    void runSearch(customQuery || query, 1);
  }

  function goToPage(nextPage: number) {
    void runSearch(query, Math.min(Math.max(nextPage, 1), totalPages));
  }

  function applyPageInput() {
    const parsed = Number.parseInt(pageInput, 10);
    if (Number.isFinite(parsed)) {
      goToPage(parsed);
    }
  }

  function applyFilterChange() {
    selectedAssetIds = new Set();
    if (configured && query.trim()) {
      void runSearch(query, 1);
    }
  }

  function applyYearFilterChange() {
    if (!selectedYear) {
      selectedMonth = '';
    }
    applyFilterChange();
  }

  function clearDateFilter() {
    selectedYear = '';
    selectedMonth = '';
    applyFilterChange();
  }

  async function trashByThreshold() {
    if (!result || trashing || thresholdValue === null) {
      return;
    }

    const confirmed = window.confirm(
      `「${query}」の検索結果から score ${thresholdValue} 以上の画像をゴミ箱に移動します。`
    );
    if (!confirmed) {
      return;
    }

    trashing = true;
    errorMessage = '';
    noticeMessage = '';

    try {
      const response = await requestJson<{
        movedCount: number;
        skippedExcludedCount: number;
        skippedDeletedCount: number;
      }>('/api/assets', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          query,
          threshold: thresholdValue,
          size: searchSize,
          year: selectedYear || null,
          month: selectedYear && selectedMonth ? selectedMonth : null
        })
      });

      noticeMessage = `${response.movedCount} 件をゴミ箱に移動しました。対象外 ${response.skippedExcludedCount} 件、削除済み ${response.skippedDeletedCount} 件はスキップしました。`;
      await runSearch(query, 1);
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : '一括移動に失敗しました';
    } finally {
      trashing = false;
    }
  }

  async function trashSelectedAssets() {
    if (selectedAssetIds.size === 0 || trashing) {
      return;
    }

    const ids = [...selectedAssetIds];
    const confirmed = window.confirm(`${ids.length} 件の指定画像をゴミ箱に移動します。`);
    if (!confirmed) {
      return;
    }

    trashing = true;
    errorMessage = '';
    noticeMessage = '';

    try {
      const response = await requestJson<{
        movedCount: number;
        skippedExcludedCount: number;
        skippedDeletedCount: number;
      }>('/api/assets', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          query,
          assetIds: ids,
          size: searchSize,
          year: selectedYear || null,
          month: selectedYear && selectedMonth ? selectedMonth : null
        })
      });

      selectedAssetIds = new Set();
      noticeMessage = `${response.movedCount} 件をゴミ箱に移動しました。削除済み ${response.skippedDeletedCount} 件はスキップしました。`;
      await runSearch(query, currentPage);
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : '指定画像の一括移動に失敗しました';
    } finally {
      trashing = false;
    }
  }

  function toggleAssetSelection(assetId: string, checked: boolean) {
    selectedAssetIds = new Set(selectedAssetIds);
    if (checked) {
      selectedAssetIds.add(assetId);
      return;
    }
    selectedAssetIds.delete(assetId);
  }

  function isAssetSelected(assetId: string) {
    return selectedAssetIds.has(assetId);
  }

  function openContextMenu(event: MouseEvent, asset: CleanerAsset) {
    event.preventDefault();
    contextMenu = {
      visible: true,
      x: Math.min(event.clientX, window.innerWidth - 244),
      y: Math.min(event.clientY, window.innerHeight - 68),
      asset
    };
  }

  function closeContextMenu() {
    contextMenu = { visible: false, x: 0, y: 0, asset: null };
  }

  function prefetchOriginalWhenVisible(node: HTMLElement, asset: CleanerAsset) {
    let currentAsset = asset;

    if (typeof IntersectionObserver === 'undefined') {
      return {
        update(nextAsset: CleanerAsset) {
          currentAsset = nextAsset;
        }
      };
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void prefetchOriginalImage(currentAsset);
          observer.unobserve(node);
        }
      },
      { threshold: 0.01 }
    );
    observer.observe(node);

    return {
      update(nextAsset: CleanerAsset) {
        if (nextAsset.id === currentAsset.id) {
          currentAsset = nextAsset;
          return;
        }
        currentAsset = nextAsset;
        observer.unobserve(node);
        observer.observe(node);
      },
      destroy() {
        observer.disconnect();
      }
    };
  }

  function prefetchOriginalImage(asset: CleanerAsset): Promise<void> {
    const currentState = originalImages.get(asset.id);
    if (currentState?.status === 'loaded') {
      return Promise.resolve();
    }
    if (currentState?.status === 'loading') {
      return currentState.promise;
    }

    const abort = new AbortController();
    const promise = (async () => {
      try {
        const response = await fetch(asset.originalUrl, {
          cache: 'reload',
          headers: { accept: 'image/*' },
          signal: abort.signal
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const blobUrl = URL.createObjectURL(await response.blob());
        try {
          await decodeImage(blobUrl);
        } catch (error) {
          URL.revokeObjectURL(blobUrl);
          throw error;
        }
        setOriginalImageState(asset.id, { status: 'loaded', url: blobUrl });
      } catch (error) {
        if (abort.signal.aborted) {
          return;
        }
        setOriginalImageState(asset.id, {
          status: 'error',
          message: error instanceof Error ? error.message : '元画像を読み込めませんでした'
        });
      }
    })();

    setOriginalImageState(asset.id, { status: 'loading', promise, abort });
    return promise;
  }

  function setOriginalImageState(assetId: string, state: OriginalImageState) {
    const previousState = originalImages.get(assetId);
    if (previousState?.status === 'loaded' && previousState.url !== (state.status === 'loaded' ? state.url : null)) {
      URL.revokeObjectURL(previousState.url);
    }
    originalImages = new Map(originalImages).set(assetId, state);
  }

  function getOriginalImageState(assetId: string) {
    return originalImages.get(assetId) ?? null;
  }

  function pruneOriginalImageStates(keepAssetIds: Set<string>) {
    const nextImages = new Map(originalImages);
    for (const [assetId, state] of nextImages) {
      if (!keepAssetIds.has(assetId)) {
        releaseOriginalImageState(state);
        nextImages.delete(assetId);
      }
    }
    originalImages = nextImages;
  }

  function releaseOriginalImageState(state: OriginalImageState) {
    if (state.status === 'loading') {
      state.abort.abort();
      return;
    }
    if (state.status === 'loaded') {
      URL.revokeObjectURL(state.url);
    }
  }

  async function decodeImage(src: string) {
    const image = new Image();
    image.decoding = 'async';
    image.src = src;
    let timeoutId = 0;
    try {
      await Promise.race([
        image.decode(),
        new Promise<never>((_, reject) => {
          timeoutId = window.setTimeout(() => reject(new Error('画像のデコードがタイムアウトしました')), 15000);
        })
      ]);
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function openAssetPreview(asset: CleanerAsset) {
    closeContextMenu();
    void prefetchOriginalImage(asset);
    if (previewAsset?.id === asset.id) {
      return;
    }
    void runPreviewTransition(asset.id, () => {
      previewAsset = asset;
    });
  }

  function closeAssetPreview(options: { animated: boolean } = { animated: true }) {
    if (!previewAsset) {
      return;
    }

    const assetId = previewAsset.id;
    if (!options.animated) {
      activePreviewTransition?.skipTransition();
      activePreviewTransition = null;
      previewTransitionToken = null;
      transitionAssetId = null;
      previewAsset = null;
      return;
    }

    void runPreviewTransition(assetId, () => {
      previewAsset = null;
    });
  }

  async function runPreviewTransition(assetId: string, updatePreview: () => void) {
    activePreviewTransition?.skipTransition();
    const token = Symbol(assetId);
    previewTransitionToken = token;
    transitionAssetId = assetId;
    await tick();

    const viewTransitionDocument = document as ViewTransitionDocument;
    if (!canUsePreviewTransition(viewTransitionDocument)) {
      updatePreview();
      await tick();
      clearPreviewTransition(token);
      return;
    }

    const transition = viewTransitionDocument.startViewTransition!(async () => {
      updatePreview();
      await tick();
    });
    activePreviewTransition = transition;

    try {
      await transition.finished;
    } catch {
      // Interrupted transitions are expected during fast repeated preview actions.
    } finally {
      clearPreviewTransition(token);
    }
  }

  function clearPreviewTransition(token: symbol) {
    if (previewTransitionToken !== token) {
      return;
    }
    previewTransitionToken = null;
    transitionAssetId = null;
    activePreviewTransition = null;
  }

  function canUsePreviewTransition(viewTransitionDocument: ViewTransitionDocument) {
    return Boolean(viewTransitionDocument.startViewTransition) && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function getPreviewTransitionName(assetId: string) {
    return `asset-preview-${assetId.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  }

  function getThumbnailTransitionStyle(assetId: string) {
    if (transitionAssetId === assetId && !previewAsset) {
      return `view-transition-name: ${getPreviewTransitionName(assetId)};`;
    }
    return '';
  }

  function getPreviewImageSrc(asset: CleanerAsset, state: OriginalImageState | null) {
    return state?.status === 'loaded' ? state.url : asset.thumbnailUrl;
  }

  function retryOriginalImage(asset: CleanerAsset | null) {
    if (asset) {
      void prefetchOriginalImage(asset);
    }
  }

  async function toggleExclusion() {
    if (!contextMenu.visible) {
      return;
    }

    const asset = contextMenu.asset;
    const method = asset.isExcluded ? 'DELETE' : 'PUT';
    closeContextMenu();
    errorMessage = '';
    noticeMessage = '';

    try {
      await requestJson(`/api/assets/${encodeURIComponent(asset.id)}/exclusion`, { method });
      await runSearch(query, currentPage);
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : '対象外設定の更新に失敗しました';
    }
  }

  function handleWindowKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      if (previewAsset) {
        event.preventDefault();
        closeAssetPreview();
        return;
      }
      closeContextMenu();
    }
  }

  function parseThresholdInput(value: string | number | undefined): number | null {
    if (value === undefined || value === '') {
      return null;
    }

    const parsed = typeof value === 'number' ? value : Number.parseFloat(value);
    if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
      return null;
    }

    return parsed;
  }

  async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, init);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.message ?? `HTTP ${response.status}`);
    }
    return payload as T;
  }
</script>

<svelte:head>
  <title>Immich Cleaner</title>
</svelte:head>

<svelte:window on:click={closeContextMenu} on:keydown={handleWindowKeydown} />

<main class="app-shell">
  <header class="keyword-bar">
    <nav class="preset-list" aria-label="検索プリセット">
      {#each presets as preset}
        <button
          class="preset-button"
          type="button"
          aria-pressed={query === preset}
          disabled={loading}
          on:click={() => selectPreset(preset)}
        >
          {preset}
        </button>
      {/each}
    </nav>

    <form class="query-form" on:submit|preventDefault={submitCustomQuery}>
      <input
        class="query-input"
        type="search"
        aria-label="検索キーワード"
        placeholder="custom keyword"
        bind:value={customQuery}
      />
      <button class="search-button" type="submit" disabled={loading}>検索</button>
    </form>
  </header>

  <aside class="control-panel" aria-label="検索コントロール">
    <section class="control-group">
      <div class="control-title">ページ</div>
      <div class="pager">
        <button class="pager-button" type="button" disabled={loading || currentPage <= 1} on:click={() => goToPage(currentPage - 1)}>
          &lt;
        </button>
        <input
          class="page-input"
          aria-label="現在のページ"
          inputmode="numeric"
          bind:value={pageInput}
          on:keydown={(event) => event.key === 'Enter' && applyPageInput()}
          on:change={applyPageInput}
        />
        <button class="pager-button" type="button" disabled={loading || currentPage >= totalPages} on:click={() => goToPage(currentPage + 1)}>
          &gt;
        </button>
      </div>
      <div class="meta-grid">
        <span>現在</span>
        <strong>{currentPage} / {totalPages}</strong>
        <span>Total</span>
        <strong>{totalItems}</strong>
      </div>
      <label class="number-field">
        <span>Per Page</span>
        <input type="number" min="1" max="500" bind:value={pageSize} on:change={applyFilterChange} />
      </label>
    </section>

    <section class="control-group">
      <label class="number-field">
        <span class="control-title">Threshold</span>
        <input type="number" min="0" max="1" step="any" bind:value={threshold} />
      </label>
    </section>

    <section class="control-group">
      <div class="control-title">フィルタリング</div>
      <label class="toggle-row">
        <input type="checkbox" bind:checked={includeExcluded} on:change={applyFilterChange} />
        <span>対象外を表示</span>
      </label>
      <label class="number-field">
        <span>年</span>
        <select bind:value={selectedYear} on:change={applyYearFilterChange}>
          <option value="">すべて</option>
          {#each yearOptions as year}
            <option value={year}>{year}</option>
          {/each}
        </select>
      </label>
      <label class="number-field">
        <span>月</span>
        <select bind:value={selectedMonth} disabled={!selectedYear} on:change={applyFilterChange}>
          <option value="">すべて</option>
          {#each monthOptions as month}
            <option value={month}>{month.padStart(2, '0')}</option>
          {/each}
        </select>
      </label>
      <button class="secondary-button" type="button" on:click={clearDateFilter}>
        年月をクリア
      </button>
    </section>

    <section class="control-group">
      <div class="control-title">アクション</div>
      <button class="danger-button" type="button" disabled={!result || loading || trashing || thresholdValue === null} on:click={trashByThreshold}>
        閾値以上をゴミ箱へ
      </button>
      <button class="danger-button" type="button" disabled={selectedCount === 0 || loading || trashing} on:click={trashSelectedAssets}>
        指定画像をゴミ箱へ
      </button>
    </section>
  </aside>

  <section class="main-area" aria-live="polite">
    <div class="status-row">
      <div class="status-pill">
        {#if result}
          {result.query} / {result.totalItems} 件
        {:else}
          Immich Cleaner
        {/if}
      </div>
      {#if loading}
        <span>検索中</span>
      {/if}
    </div>

    {#if !configLoadFailed && !configured}
      <div class="error-box">IMMICH_URL と IMMICH_API_KEY を設定してください。</div>
    {/if}

    {#if errorMessage}
      <div class="error-box">{errorMessage}</div>
    {/if}

    {#if noticeMessage}
      <div class="notice-box">{noticeMessage}</div>
    {/if}

    {#if result?.items.length}
    <div class="asset-list">
      {#each result.items as asset (asset.id)}
      <article
            class:is-excluded={asset.isExcluded}
            class="asset-row"
            on:contextmenu={(event) => openContextMenu(event, asset)}
          >
            <label class="asset-select">
              <input
                type="checkbox"
                aria-label={`${asset.originalFileName ?? asset.id} を選択`}
                checked={isAssetSelected(asset.id)}
                on:change={(event) => toggleAssetSelection(asset.id, event.currentTarget.checked)}
              />
            </label>
            <div class="thumb-wrap" use:prefetchOriginalWhenVisible={asset}>
              <button
                class="thumb-button"
                type="button"
                aria-label={`${asset.originalFileName ?? asset.id} を拡大表示`}
                on:click={() => openAssetPreview(asset)}
              >
                <img
                  class="thumb-image"
                  loading="lazy"
                  src={asset.thumbnailUrl}
                  alt={asset.originalFileName ?? asset.id}
                  style={getThumbnailTransitionStyle(asset.id)}
                />
              </button>
              {#if asset.isExcluded}
                <span class="badge thumb-badge">フィルタリング対象外</span>
              {/if}
            </div>
            <div class="asset-body">
              <div class="file-name">{asset.originalFileName ?? asset.id}</div>
              {#if asset.originalPath}
                <div class="file-path">{asset.originalPath}</div>
              {/if}
              {#if asset.exclusionReason === 'rescued'}
                <span class="badge">rescued</span>
              {:else if asset.isExcluded}
                <span class="badge">manual</span>
              {/if}
            </div>
            <div class="score-box">
              <span>Score</span>
              <span class="score-value">{formatScore(asset.score)}</span>
            </div>
          </article>
        {/each}
      </div>
    {:else if result && !loading}
      <div class="empty-state">表示対象なし</div>
    {:else if !result && !loading}
      <div class="empty-state">キーワードを選択</div>
    {/if}
  </section>

  {#if contextMenu.visible}
    <div
      class="context-menu"
      style={`left: ${contextMenu.x}px; top: ${contextMenu.y}px;`}
      role="menu"
      tabindex="-1"
    >
      <button type="button" role="menuitem" on:click={toggleExclusion}>
        {contextMenu.asset.isExcluded ? '対象に戻す' : 'フィルタリング対象外に設定'}
      </button>
    </div>
  {/if}

  {#if previewAsset}
    {@const previewState = getOriginalImageState(previewAsset.id)}
    <div
      class="image-preview"
      role="dialog"
      aria-modal="true"
      aria-label={`${previewAsset.originalFileName ?? previewAsset.id} の拡大表示`}
    >
      <button
        class="preview-backdrop"
        type="button"
        aria-label="拡大表示を閉じる"
        on:click={() => closeAssetPreview()}
      ></button>
      <figure class="preview-figure">
        <div class="preview-media">
          <img
            class:uses-placeholder={previewState?.status !== 'loaded'}
            class="preview-image"
            src={getPreviewImageSrc(previewAsset, previewState)}
            alt={previewAsset.originalFileName ?? previewAsset.id}
            style={`view-transition-name: ${getPreviewTransitionName(previewAsset.id)};`}
          />
          {#if !previewState || previewState.status === 'loading'}
            <div class="preview-state" aria-label="元画像を読み込み中" aria-live="polite">
              <span class="loading-icon" aria-hidden="true"></span>
            </div>
          {:else if previewState.status === 'error'}
            <div class="preview-state is-error" aria-live="polite">
              <span>元画像を読み込めませんでした</span>
              <button type="button" on:click={() => retryOriginalImage(previewAsset)}>再試行</button>
            </div>
          {/if}
        </div>
        <figcaption class="preview-caption">{previewAsset.originalFileName ?? previewAsset.id}</figcaption>
      </figure>
      <button class="preview-close" type="button" aria-label="拡大表示を閉じる" on:click={() => closeAssetPreview()}>
        &times;
      </button>
    </div>
  {/if}
</main>
