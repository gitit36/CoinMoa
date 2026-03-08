
export enum ExchangeName {
  UPBIT = 'Upbit',
  BITHUMB = 'Bithumb',
  COINONE = 'Coinone',
  KORBIT = 'Korbit',
  BINANCE = 'Binance',
  BYBIT = 'Bybit',
  METAMASK = 'Metamask',
  HYPERLIQUID = 'Hyperliquid',
  LIGHTER = 'Lighter',
  EDGEX = 'EdgeX'
}

export type TransactionType = 'DEPOSIT' | 'WITHDRAWAL' | 'BUY' | 'SELL' | 'TRANSFER' | 'LIQUIDATION';

export interface Transaction {
  id: string;
  exchange: ExchangeName;
  timestamp: number;
  type: TransactionType;
  pair: string;
  amount: number;
  price: number;
  fee: number;
  currency: string;
  krwValue: number;
  exchangeRate?: number; // 해외 거래소용 환율 정보
  toExchange?: ExchangeName;
}

export interface ExchangeAccount {
  name: ExchangeName;
  apiKey: string;
  apiSecret: string;
  connected: boolean;
  lastSyncedAt?: number;
  missingEnv?: string[];
  managedBy?: 'env' | 'browser';
  error?: string;
}

export interface PortfolioSummary {
  totalBalanceKRW: number;
  totalOnRampGross: number;
  totalOnRampNet: number;
  pnlAmount: number;
  pnlPercentage: number;
}

export interface MarketTicker {
  symbol: string;
  krwPrice: number;
  krwChange: number;
  usdPrice: number;
  usdChange: number;
}
