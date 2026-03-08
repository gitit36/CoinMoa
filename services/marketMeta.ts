import { ExchangeName } from '../types.ts';

export interface AssetCatalogEntry {
  symbol: string;
  display_name_ko?: string | null;
  english_name?: string | null;
  aliases?: string[];
  exchanges?: string[];
  preferred_source?: string | null;
  is_cmc_top_200?: boolean;
  upbit?: {
    markets?: string[];
    korean_name?: string | null;
    english_name?: string | null;
  };
  bithumb?: {
    markets?: string[];
    korean_name?: string | null;
    english_name?: string | null;
  };
  binance?: {
    markets?: string[];
  };
  cmc?: {
    id: number;
    slug?: string;
    name?: string;
    rank?: number;
  } | null;
  image_url?: string | null;
}

export type AssetCatalog = Record<string, AssetCatalogEntry>;

const EXCHANGE_LABELS_KO: Record<string, string> = {
  [ExchangeName.UPBIT]: '업비트',
  [ExchangeName.BITHUMB]: '빗썸',
  [ExchangeName.BINANCE]: '바이낸스',
  [ExchangeName.LIGHTER]: '라이터',
  [ExchangeName.HYPERLIQUID]: '하이퍼리퀴드',
  [ExchangeName.COINONE]: '코인원',
  [ExchangeName.KORBIT]: '코빗',
  [ExchangeName.METAMASK]: '메타마스크',
  [ExchangeName.BYBIT]: '바이비트',
  [ExchangeName.EDGEX]: '엣지엑스',
};

const EXCHANGE_SEARCH_ALIASES: Record<string, string[]> = {
  [ExchangeName.UPBIT]: ['upbit', '업비트'],
  [ExchangeName.BITHUMB]: ['bithumb', '빗썸'],
  [ExchangeName.BINANCE]: ['binance', '바이낸스'],
  [ExchangeName.LIGHTER]: ['lighter', '라이터'],
  [ExchangeName.HYPERLIQUID]: ['hyperliquid', '하이퍼리퀴드'],
  [ExchangeName.COINONE]: ['coinone', '코인원'],
  [ExchangeName.KORBIT]: ['korbit', '코빗'],
  [ExchangeName.METAMASK]: ['metamask', '메타마스크'],
  [ExchangeName.BYBIT]: ['bybit', '바이비트'],
  [ExchangeName.EDGEX]: ['edgex', '엣지엑스'],
};

let assetCatalogPromise: Promise<AssetCatalog> | null = null;

export const getExchangeLabel = (exchange: string) => EXCHANGE_LABELS_KO[exchange] || exchange;

export const getExchangeSearchAliases = (exchange: string) => EXCHANGE_SEARCH_ALIASES[exchange] || [exchange.toLowerCase()];

export const getAssetMeta = (catalog: AssetCatalog, symbol: string) => catalog[symbol.toUpperCase()];

export const getAssetDisplayName = (catalog: AssetCatalog, symbol: string) => {
  const entry = getAssetMeta(catalog, symbol);
  return entry?.display_name_ko || entry?.english_name || symbol;
};

export const getAssetDisplayNameForExchange = (catalog: AssetCatalog, symbol: string, exchange?: string) => {
  const entry = getAssetMeta(catalog, symbol);
  if (!entry) return symbol;

  if (exchange === ExchangeName.UPBIT) {
    return entry.upbit?.korean_name || entry.display_name_ko || entry.english_name || symbol;
  }
  if (exchange === ExchangeName.BITHUMB) {
    return entry.bithumb?.korean_name || entry.display_name_ko || entry.english_name || symbol;
  }
  return entry.display_name_ko || entry.english_name || symbol;
};

export const getAssetImageUrl = (catalog: AssetCatalog, symbol: string) => {
  const entry = getAssetMeta(catalog, symbol);
  return entry?.image_url || `https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/${symbol.toLowerCase()}.png`;
};

export const getAssetSearchAliases = (catalog: AssetCatalog, symbol: string) => {
  const entry = getAssetMeta(catalog, symbol);
  return entry?.aliases || [symbol];
};

export const getAssetSourceLabel = (catalog: AssetCatalog, symbol: string) => {
  const entry = getAssetMeta(catalog, symbol);
  const source = entry?.preferred_source;

  if (source === 'upbit') return 'Upbit';
  if (source === 'bithumb') return 'Bithumb';
  if (source === 'binance') return 'Binance';
  if (source === 'cmc_top_200') return 'CMC Top 200';
  if (source === 'cmc') return 'CMC';
  return 'Symbol';
};

export const getAssetRankLabel = (catalog: AssetCatalog, symbol: string) => {
  const entry = getAssetMeta(catalog, symbol);
  const rank = entry?.cmc?.rank;
  return typeof rank === 'number' ? `CMC #${rank}` : null;
};

export const getPairSubtitle = (catalog: AssetCatalog, pair: string, exchange?: string) => {
  const [base, quote] = pair.split('/');
  const baseLabel = getAssetDisplayNameForExchange(catalog, base || pair, exchange);

  if (!quote) return baseLabel;
  if (quote === 'KRW') return `${baseLabel} · 원화마켓`;
  if (quote === 'USDT') return `${baseLabel} · 테더마켓`;
  if (quote === 'BTC') return `${baseLabel} · 비트코인마켓`;
  return `${baseLabel} · ${quote}`;
};

export const loadAssetCatalog = async (): Promise<AssetCatalog> => {
  if (!assetCatalogPromise) {
    assetCatalogPromise = fetch('/assets/domestic-asset-catalog.json')
      .then((response) => {
        if (!response.ok) throw new Error('Failed to load asset catalog');
        return response.json();
      })
      .then((payload) => payload.assets as AssetCatalog)
      .catch(() => ({}));
  }
  return assetCatalogPromise;
};
