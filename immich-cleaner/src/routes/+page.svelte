<script lang="ts">
  import { onMount } from 'svelte';
  import { formatScore } from '$lib/score';

  type CleanerAsset = {
    id: string;
    score: number;
    originalFileName: string | null;
    originalPath: string | null;
    thumbnailUrl: string;
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
  let threshold = 0.75;
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

  async function runSearch(nextQuery = query, nextPage = 1) {
    const normalizedQuery = nextQuery.trim();
    if (!normalizedQuery) {
      errorMessage = '検索キーワードを入力してください';
      return;
    }

    if (normalizedQuery !== query) {
      selectedAssetIds = new Set();
    }
    query = normalizedQuery;
    loading = true;
    errorMessage = '';
    noticeMessage = '';
    closeContextMenu();

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
    if (!result || trashing) {
      return;
    }

    const confirmed = window.confirm(
      `「${query}」の検索結果から score ${threshold} 以上の画像をゴミ箱に移動します。`
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
          threshold,
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
      closeContextMenu();
    }
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
      <button class="danger-button" type="button" disabled={!result || loading || trashing} on:click={trashByThreshold}>
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
            <div class="thumb-wrap">
              <img loading="lazy" src={asset.thumbnailUrl} alt={asset.originalFileName ?? asset.id} />
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
</main>
