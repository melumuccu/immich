export type ExclusionReason = 'manual' | 'rescued';

export type ExcludedAsset = {
  assetId: string;
  reason: ExclusionReason;
  updatedAt: string;
};

export type SmartSearchAsset = {
  id: string;
  score: number;
  type: string;
  originalFileName: string | null;
  originalPath: string | null;
  isDeleted: boolean;
};

export type CleanerAsset = SmartSearchAsset & {
  thumbnailUrl: string;
  isExcluded: boolean;
  exclusionReason: ExclusionReason | null;
};

export type SearchPage = {
  query: string;
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
  includeExcluded: boolean;
  searchSize: number;
  items: CleanerAsset[];
};

export type TrashResult = {
  query: string;
  threshold: number | null;
  movedCount: number;
  skippedExcludedCount: number;
  skippedDeletedCount: number;
  ids: string[];
};
