
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { LayoutDashboard, ArrowLeftRight, FileText, Settings, ShieldCheck, TrendingUp, Activity } from 'lucide-react';
import { Transaction, ExchangeAccount, ExchangeName, PortfolioSummary, MarketTicker } from './types.ts';
import { generateMockTransactions } from './services/mockData.ts';
import { getTaxInsights } from './services/geminiService.ts';
import { AssetCatalog, loadAssetCatalog } from './services/marketMeta.ts';
import Dashboard from './components/Dashboard.tsx';
import ExchangeManager from './components/ExchangeManager.tsx';
import TransactionTable from './components/TransactionTable.tsx';
import TaxReport from './components/TaxReport.tsx';

const TARGET_PORTFOLIO_VALUE = 300000000;
const TICKER_SYMBOLS = ['BTC', 'ETH', 'SOL', 'XRP'] as const;
const UPBIT_TICKER_MARKETS = TICKER_SYMBOLS.map((symbol) => `KRW-${symbol}`).join(',');
const BINANCE_TICKER_SYMBOLS = TICKER_SYMBOLS.map((symbol) => `${symbol}USDT`).join(',');

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'transactions' | 'tax' | 'exchanges'>('dashboard');
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<ExchangeAccount[]>([
    { name: ExchangeName.UPBIT, apiKey: '', apiSecret: '', connected: false },
    { name: ExchangeName.BITHUMB, apiKey: '', apiSecret: '', connected: false },
    { name: ExchangeName.BINANCE, apiKey: '', apiSecret: '', connected: false },
    { name: ExchangeName.LIGHTER, apiKey: '', apiSecret: '', connected: false },
    { name: ExchangeName.HYPERLIQUID, apiKey: '', apiSecret: '', connected: false }
  ]);
  const [aiInsights, setAiInsights] = useState<string>('');
  const [isLoadingInsights, setIsLoadingInsights] = useState(false);
  const [marketPrices, setMarketPrices] = useState<MarketTicker[]>([
    { symbol: 'BTC', krwPrice: 95420000, krwChange: 1.2, usdPrice: 68120, usdChange: 0.9 },
    { symbol: 'ETH', krwPrice: 4650000, krwChange: -0.5, usdPrice: 3325, usdChange: -0.4 },
    { symbol: 'SOL', krwPrice: 218000, krwChange: 2.1, usdPrice: 154, usdChange: 1.8 },
    { symbol: 'XRP', krwPrice: 842, krwChange: -1.1, usdPrice: 0.6, usdChange: -0.8 },
  ]);
  const [isLive, setIsLive] = useState(false);
  const [assetCatalog, setAssetCatalog] = useState<AssetCatalog>({});
  
  const priceRef = useRef(marketPrices);
  const isLiveRef = useRef(isLive);

  const fetchPrices = async () => {
    try {
      const [upbitResponse, binanceResponse] = await Promise.all([
        fetch(`https://api.upbit.com/v1/ticker?markets=${UPBIT_TICKER_MARKETS}`, { mode: 'cors' }),
        fetch(`https://api.binance.com/api/v3/ticker/24hr?symbols=${encodeURIComponent(JSON.stringify(BINANCE_TICKER_SYMBOLS))}`, { mode: 'cors' }),
      ]);
      if (!upbitResponse.ok || !binanceResponse.ok) throw new Error('Network response was not ok');

      const [upbitData, binanceData] = await Promise.all([upbitResponse.json(), binanceResponse.json()]);

      const upbitBySymbol = new Map<string, any>(
        upbitData.map((item: any) => [String(item.market).replace('KRW-', ''), item]),
      );
      const binanceBySymbol = new Map<string, any>(
        binanceData.map((item: any) => [String(item.symbol).replace('USDT', ''), item]),
      );

      const newPrices: MarketTicker[] = TICKER_SYMBOLS.map((symbol) => {
        const upbitTicker = upbitBySymbol.get(symbol);
        const binanceTicker = binanceBySymbol.get(symbol);

        return {
          symbol,
          krwPrice: Number(upbitTicker?.trade_price ?? 0),
          krwChange: Number(upbitTicker?.signed_change_rate ?? 0) * 100,
          usdPrice: Number(binanceTicker?.lastPrice ?? 0),
          usdChange: Number(binanceTicker?.priceChangePercent ?? 0),
        };
      });

      setMarketPrices(newPrices);
      priceRef.current = newPrices;
      isLiveRef.current = true;
      setIsLive(true);
    } catch {
      isLiveRef.current = false;
      setIsLive(false);
      simulatePriceMovement();
    }
  };

  const simulatePriceMovement = () => {
    const drift = () => (1 + (Math.random() * 0.0004 - 0.0002));
    const nextPrices = priceRef.current.map((ticker) => ({
      ...ticker,
      krwPrice: ticker.krwPrice * drift(),
      krwChange: ticker.krwChange + (Math.random() * 0.1 - 0.05),
      usdPrice: ticker.usdPrice * drift(),
      usdChange: ticker.usdChange + (Math.random() * 0.1 - 0.05),
    }));
    setMarketPrices(nextPrices);
    priceRef.current = nextPrices;
  };

  useEffect(() => {
    const data = generateMockTransactions();
    setTransactions(data);
    fetchPrices();
    const interval = setInterval(() => {
      if (isLiveRef.current) fetchPrices();
      else {
        simulatePriceMovement();
        if (Math.random() > 0.9) fetchPrices();
      }
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    loadAssetCatalog().then(setAssetCatalog).catch(() => setAssetCatalog({}));
  }, []);

  const portfolioSummary = useMemo((): PortfolioSummary => {
    const deposits = transactions.filter(t => t.type === 'DEPOSIT' && t.currency === 'KRW');
    const withdrawals = transactions.filter(t => t.type === 'WITHDRAWAL' && t.currency === 'KRW');
    const grossOnRamp = deposits.reduce((acc, t) => acc + t.amount, 0);
    const totalWithdraw = withdrawals.reduce((acc, t) => acc + t.amount, 0);
    const currentMarketValue = TARGET_PORTFOLIO_VALUE;
    const netInvested = grossOnRamp - totalWithdraw;
    const pnl = currentMarketValue - netInvested;
    return {
      totalBalanceKRW: currentMarketValue,
      totalOnRampGross: grossOnRamp,
      totalOnRampNet: netInvested,
      pnlAmount: pnl,
      pnlPercentage: netInvested !== 0 ? (pnl / netInvested) * 100 : 0
    };
  }, [transactions]);

  const handleFetchInsights = async () => {
    setIsLoadingInsights(true);
    const insights = await getTaxInsights(transactions);
    setAiInsights(insights || '');
    setIsLoadingInsights(false);
  };

  const NavItem = ({ id, icon: Icon, label }: { id: typeof activeTab, icon: any, label: string }) => (
    <button
      onClick={() => setActiveTab(id)}
      className={`flex items-center gap-3 px-4 py-3 rounded-[14px] transition-all ${
        activeTab === id 
          ? 'bg-[#1f2937] text-white font-bold shadow-[inset_0_0_0_1px_rgba(255,255,255,0.04)]' 
          : 'text-[#9aa4b2] hover:bg-white/6 hover:text-white'
      }`}
    >
      <Icon size={18} />
      <span className="text-sm md:text-[15px]">{label}</span>
    </button>
  );

  return (
    <div className="min-h-screen bg-[#eef2f6] pb-20 md:pb-0">
      <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="hidden md:flex w-[288px] shrink-0 flex-col bg-[#0f172a] p-6 text-white">
        <div className="mb-10 flex items-center gap-3 px-2">
          <div className="rounded-[12px] bg-[#2463eb] p-2 text-white shadow-[0_10px_24px_rgba(36,99,235,0.25)]">
            <ShieldCheck size={24} />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight">CoinMoa Console</h1>
            <p className="mt-0.5 text-[12px] font-medium text-[#94a3b8]">Crypto tax workspace</p>
          </div>
        </div>

        <div className="mb-8 rounded-[18px] border border-white/10 bg-white/5 px-4 py-5">
          <p className="text-[11px] font-black uppercase tracking-[0.22em] text-[#94a3b8]">Preview Workspace</p>
          <p className="mt-2 text-[18px] font-black leading-tight text-white">실전 전 점검용 화면</p>
          <p className="mt-2 text-[13px] font-medium leading-relaxed text-[#94a3b8]">
            거래 흐름, 세무 리포트, 연결 화면을 한 화면에서 빠르게 확인하는 프로토타입입니다.
          </p>
        </div>
        
        <nav className="flex flex-1 flex-col space-y-1">
          <NavItem id="dashboard" icon={LayoutDashboard} label="홈" />
          <NavItem id="transactions" icon={ArrowLeftRight} label="내역" />
          <NavItem id="tax" icon={FileText} label="세금" />
          <div className="flex-1" />
          <NavItem id="exchanges" icon={Settings} label="설정" />
        </nav>
        
        <div className="mt-auto rounded-[18px] border border-white/10 bg-white/5 px-4 py-4">
          <div className="flex items-center gap-2 text-[#cbd5e1]">
            <div className={`h-2 w-2 rounded-full ${isLive ? 'bg-emerald-400' : 'bg-slate-400'}`} />
            <span className="text-xs font-semibold">
              {isLive ? '실시간 시세 연결됨' : '시뮬레이션 모드'}
            </span>
          </div>
          <p className="mt-2 text-[12px] font-medium text-[#94a3b8]">데스크톱 중심 검토용 레이아웃</p>
        </div>
      </aside>

      <nav className="fixed bottom-0 left-0 right-0 z-40 flex items-center justify-between border-t border-[#e5e8eb] bg-white/92 px-4 py-2 backdrop-blur-xl md:hidden">
        <NavItem id="dashboard" icon={LayoutDashboard} label="홈" />
        <NavItem id="transactions" icon={ArrowLeftRight} label="내역" />
        <NavItem id="tax" icon={FileText} label="세금" />
        <NavItem id="exchanges" icon={Settings} label="설정" />
      </nav>

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-[1520px] px-5 py-6 md:px-8 lg:px-10 xl:px-12">
        <header className="mb-8 flex flex-col gap-4 rounded-[22px] border border-[#e5e8eb] bg-white px-6 py-5 shadow-[0_12px_30px_rgba(15,23,42,0.04)] lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="pill-label">
              <Activity size={12} />
              DESKTOP REVIEW
            </div>
            <h2 className="mt-3 text-2xl font-black text-[#191f28] md:text-[30px]">
              {activeTab === 'dashboard' && '투자 요약'}
              {activeTab === 'exchanges' && '설정'}
              {activeTab === 'transactions' && '거래 내역'}
              {activeTab === 'tax' && '세금 리포트'}
            </h2>
            <p className="mt-2 text-[14px] font-medium text-[#7f8b99]">
              {activeTab === 'dashboard' && '자산 현황과 리스크를 한 번에 확인합니다.'}
              {activeTab === 'exchanges' && '읽기 전용 연결만 가정한 보안 중심 설정 화면입니다.'}
              {activeTab === 'transactions' && '모든 거래를 탐색하고 내보낼 수 있습니다.'}
              {activeTab === 'tax' && '예상 과세 구간과 제출 전 체크 포인트를 보여줍니다.'}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-3">
            <div className="hidden rounded-[16px] bg-[#f6f8fb] px-4 py-3 sm:block">
              <p className="text-[11px] font-black tracking-[0.16em] text-[#8b95a1]">MODE</p>
              <p className="mt-1 text-[14px] font-black text-[#191f28]">{isLive ? 'LIVE TICKER' : 'MOCK DATA'}</p>
            </div>
            <button
              onClick={handleFetchInsights}
              disabled={isLoadingInsights}
              className="flex shrink-0 items-center justify-center gap-2 rounded-[14px] bg-[#111827] px-4 py-3 font-bold text-white transition-all hover:bg-[#0b1220] disabled:opacity-50 sm:px-5"
            >
              <TrendingUp size={18} />
              <span className="hidden text-sm sm:inline">{isLoadingInsights ? '분석 중' : 'AI 인사이트'}</span>
            </button>
          </div>
        </header>

        <div className="pb-4">
          {activeTab === 'dashboard' && <Dashboard summary={portfolioSummary} transactions={transactions} insights={aiInsights} livePrices={marketPrices} assetCatalog={assetCatalog} />}
          {activeTab === 'exchanges' && <ExchangeManager accounts={accounts} setAccounts={setAccounts} />}
          {activeTab === 'transactions' && <TransactionTable transactions={transactions} assetCatalog={assetCatalog} />}
          {activeTab === 'tax' && <TaxReport transactions={transactions} summary={portfolioSummary} />}
        </div>
        </div>
      </main>
      </div>
    </div>
  );
};

export default App;
