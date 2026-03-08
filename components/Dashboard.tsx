import React, { useMemo, useState, useEffect } from 'react';
import {
  AlertCircle,
  ArrowUpRight,
  Clock,
  LayoutList,
  PieChart as PieChartIcon,
  Sparkles,
  TrendingUp,
  WalletCards,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { PortfolioSummary, Transaction, MarketTicker } from '../types.ts';
import { AssetCatalog, getAssetDisplayName, getAssetImageUrl, getAssetRankLabel, getAssetSourceLabel, getExchangeLabel } from '../services/marketMeta.ts';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, PieChart, Pie, Cell } from 'recharts';

interface DashboardProps {
  summary: PortfolioSummary;
  transactions: Transaction[];
  insights?: string;
  livePrices?: MarketTicker[];
  assetCatalog: AssetCatalog;
}

type TimeFrame = '일' | '주' | '월' | '년';

const COLORS = ['#3182f7', '#21b8da', '#2d3a49', '#6b7a90', '#9aa7b5', '#d7dee6'];
const SurfaceCard: React.FC<{ children: React.ReactNode; className?: string }> = ({ children, className }) => (
  <div className={`surface-card rounded-[24px] p-6 ${className || ''}`}>
    {children}
  </div>
);

const AssetSymbolIcon: React.FC<{ symbol: string; imageUrl?: string | null }> = ({ symbol, imageUrl }) => {
  const [hasImageError, setHasImageError] = useState(false);
  const badgeLabel = symbol.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 5) || '?';

  if (!imageUrl || hasImageError) {
    return (
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[#edf2f7] bg-[linear-gradient(135deg,#ffffff_0%,#f2f5f8_100%)] px-1 text-[11px] font-black tracking-[-0.02em] text-[#191f28] shadow-sm">
        {badgeLabel}
      </div>
    );
  }

  return (
    <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[#edf2f7] bg-white shadow-sm">
      <img
        src={imageUrl}
        alt={symbol}
        className="h-6 w-6"
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setHasImageError(true)}
      />
    </div>
  );
};

const formatCompactCurrency = (value: number, currency: 'KRW' | 'USD') => {
  if (currency === 'USD') {
    return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  return `${Math.round(value).toLocaleString()}원`;
};

const formatYAxis = (value: number) => {
  const absVal = Math.abs(value);
  if (absVal >= 100000000) return `${(value / 100000000).toFixed(1)}억`;
  if (absVal >= 10000) return `${(value / 10000).toLocaleString()}만`;
  return value.toLocaleString();
};

const formatInsightText = (text?: string) => {
  if (!text) {
    return [
      '아직 AI 분석이 없습니다.',
      '우측 상단의 AI 절세 버튼을 눌러 현재 포트폴리오 기준으로 핵심 포인트를 받아보세요.',
    ];
  }

  return text
    .split('\n')
    .map((line) => line.replace(/^#+\s*/, '').trim())
    .filter(Boolean)
    .slice(0, 6);
};

const TravelRuleBanner: React.FC<{ transactions: Transaction[] }> = ({ transactions }) => {
  const [timeLeft, setTimeLeft] = useState<string | null>(null);

  useEffect(() => {
    const checkTravelRule = () => {
      const latestKrwDeposit = transactions
        .filter((t) => t.type === 'DEPOSIT' && t.currency === 'KRW')
        .sort((a, b) => b.timestamp - a.timestamp)[0];

      if (!latestKrwDeposit) {
        setTimeLeft(null);
        return;
      }

      const diff = Date.now() - latestKrwDeposit.timestamp;
      const twentyFourHours = 24 * 60 * 60 * 1000;

      if (diff < twentyFourHours) {
        const remaining = twentyFourHours - diff;
        const h = Math.floor(remaining / (60 * 60 * 1000));
        const m = Math.floor((remaining % (60 * 60 * 1000)) / (60 * 1000));
        const s = Math.floor((remaining % (60 * 1000)) / 1000);
        setTimeLeft(`${h}시간 ${m}분 ${s}초`);
      } else {
        setTimeLeft(null);
      }
    };

    checkTravelRule();
    const timer = setInterval(checkTravelRule, 1000);
    return () => clearInterval(timer);
  }, [transactions]);

  if (!timeLeft) return null;

  return (
    <div className="rounded-[22px] border border-[#ffd8d2] bg-[linear-gradient(135deg,#fff7f5_0%,#fff0ed_100%)] px-5 py-4 shadow-[0_10px_30px_rgba(255,86,48,0.08)]">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-full bg-[#ff5c39] p-2 text-white shadow-sm">
            <AlertCircle size={18} />
          </div>
          <div>
            <p className="text-[14px] font-black text-[#191f28]">트래블룰 출금 제한이 아직 남아 있습니다</p>
            <p className="mt-1 text-[13px] font-medium leading-relaxed text-[#6a7789]">
              최근 KRW 입금 기준으로 24시간 이내라 외부 거래소 또는 지갑으로의 출금을 지금은 바로 진행하기 어렵습니다.
            </p>
          </div>
        </div>
        <div className="inline-flex items-center gap-2 self-start rounded-full bg-white px-4 py-2 text-[13px] font-black text-[#ff5c39] shadow-sm">
          <Clock size={14} />
          {timeLeft}
        </div>
      </div>
    </div>
  );
};

const Dashboard: React.FC<DashboardProps> = ({ summary, transactions, insights, livePrices, assetCatalog }) => {
  const [breakdownView, setBreakdownView] = useState<'list' | 'chart'>('list');
  const [displayCurrency, setDisplayCurrency] = useState<'KRW' | 'USD'>('KRW');
  const [timeFrame, setTimeFrame] = useState<TimeFrame>('월');
  const [isAssetExpanded, setIsAssetExpanded] = useState(false);

  const marketData = useMemo(
    () => (livePrices || []).map((ticker) => ({
      label: ticker.symbol,
      value: displayCurrency === 'KRW' ? ticker.krwPrice : ticker.usdPrice,
      change: `${(displayCurrency === 'KRW' ? ticker.krwChange : ticker.usdChange).toFixed(1)}%`,
      pos: (displayCurrency === 'KRW' ? ticker.krwChange : ticker.usdChange) > 0,
    })),
    [displayCurrency, livePrices],
  );

  const assetBreakdown = useMemo(() => {
    const assets: Record<string, { amount: number; value: number }> = {};
    transactions.forEach((tx) => {
      if (tx.currency === 'KRW') return;
      if (!assets[tx.currency]) assets[tx.currency] = { amount: 0, value: 0 };

      if (tx.type === 'BUY' || tx.type === 'DEPOSIT') {
        assets[tx.currency].amount += tx.amount;
        assets[tx.currency].value += tx.krwValue || tx.amount * tx.price;
      } else if (tx.type === 'SELL' || tx.type === 'WITHDRAWAL' || tx.type === 'LIQUIDATION') {
        const ratio = assets[tx.currency].amount > 0 ? Math.min(1, tx.amount / assets[tx.currency].amount) : 0;
        assets[tx.currency].value -= assets[tx.currency].value * ratio;
        assets[tx.currency].amount -= tx.amount;
      }
    });

    const rawBreakdown = Object.entries(assets)
      .filter(([, data]) => data.amount > 0.0001)
      .map(([symbol, data]) => ({ symbol, amount: data.amount, currentValue: Math.max(0, data.value) }))
      .sort((a, b) => b.currentValue - a.currentValue);

    const totalRawValue = rawBreakdown.reduce((sum, asset) => sum + asset.currentValue, 0) || 1;
    const scale = summary.totalBalanceKRW / totalRawValue;

    return rawBreakdown.map((asset) => ({
      ...asset,
      currentValue: Math.round(asset.currentValue * scale),
    }));
  }, [summary.totalBalanceKRW, transactions]);

  const exchangeBreakdown = useMemo(() => {
    const total = transactions.reduce((sum, tx) => sum + Math.abs(tx.krwValue), 0) || 1;
    const byExchange: Record<string, number> = {};

    transactions.forEach((tx) => {
      const key = String(tx.exchange);
      byExchange[key] = (byExchange[key] || 0) + Math.abs(tx.krwValue);
    });

    return (Object.entries(byExchange) as Array<[string, number]>)
      .map(([name, value]) => ({
        name,
        value,
        share: Math.round((value / total) * 100),
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 4);
  }, [transactions]);

  const chartData = useMemo(() => {
    const count = timeFrame === '일' ? 12 : timeFrame === '주' ? 7 : timeFrame === '월' ? 15 : 12;
    const base = summary.pnlAmount || summary.totalBalanceKRW * 0.08;
    return Array.from({ length: count }, (_, index) => ({
      name:
        timeFrame === '일'
          ? `${index * 2}시`
          : timeFrame === '주'
            ? `D-${7 - index}`
            : timeFrame === '월'
              ? `${(index + 1) * 2}일`
              : `${index + 1}월`,
      pnl: base * (0.82 + Math.random() * 0.34),
    }));
  }, [summary.pnlAmount, summary.totalBalanceKRW, timeFrame]);

  const displayedAssets = isAssetExpanded ? assetBreakdown : assetBreakdown.slice(0, 5);
  const insightLines = useMemo(() => formatInsightText(insights), [insights]);
  const buyCount = transactions.filter((tx) => tx.type === 'BUY').length;
  const activeAssetCount = assetBreakdown.length;
  const activeExchangeCount = new Set(transactions.map((tx) => tx.exchange)).size;

  return (
    <div className="space-y-6">
      <TravelRuleBanner transactions={transactions} />

      <SurfaceCard className="p-4 md:p-5">
        <div className="space-y-4">
          <div className="rounded-[24px] border border-[#e5e8eb] bg-[linear-gradient(180deg,#fbfcff_0%,#f4f7fb_100%)] px-5 py-7 md:px-6 md:py-8">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-3 text-[11px] font-black tracking-[0.2em] text-[#7f8b99]">
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[#dbe5f0] bg-white text-[#2463eb] shadow-sm">
                    <WalletCards size={12} />
                  </span>
                  <span>PORTFOLIO OVERVIEW</span>
                  <span className="hidden h-px w-16 bg-[#dbe5f0] md:block" />
                </div>
                <h3 className="currency-fit mt-4 text-[clamp(1.7rem,4vw,2.25rem)] font-black tracking-tight text-[#191f28]">
                  {formatCompactCurrency(summary.totalBalanceKRW, displayCurrency)}
                </h3>
                <p className="mt-2 hidden max-w-2xl text-[14px] font-medium leading-relaxed text-[#6b7684] md:block">
                  총 입금, 보유 자산, 추정 손익을 데스크톱에서 빠르게 스캔할 수 있게 요약한 상단 영역입니다. 핵심 수치와 차트는 아래 카드에서 이어집니다.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3 lg:w-[min(42%,420px)] lg:flex-none">
                <div className="min-w-0 rounded-[18px] border border-[#e5e8eb] bg-white px-4 py-4 shadow-[0_10px_24px_rgba(15,23,42,0.04)]">
                  <p className="text-[12px] font-bold text-[#7f8b99]">평가 손익</p>
                  <p className="currency-fit mt-2 text-[1.05rem] font-black tracking-[-0.03em] text-[#191f28] lg:text-[clamp(0.82rem,1.15vw,1.08rem)]">
                    {summary.pnlAmount >= 0 ? '+' : '-'}
                    {formatCompactCurrency(Math.abs(summary.pnlAmount), displayCurrency)}
                  </p>
                  <p className="mt-1 text-[12px] font-bold text-[#7f8b99]">{summary.pnlPercentage.toFixed(1)}%</p>
                </div>
                <div className="min-w-0 rounded-[18px] border border-[#e5e8eb] bg-white px-4 py-4 shadow-[0_10px_24px_rgba(15,23,42,0.04)]">
                  <p className="text-[12px] font-bold text-[#7f8b99]">활성 자산</p>
                  <p className="mt-2 text-[22px] font-black text-[#191f28]">{activeAssetCount}개</p>
                  <p className="mt-1 text-[12px] font-bold text-[#7f8b99]">보유 코인 기준</p>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-[#edf2f7] bg-[#f8fafc] px-5 py-5 md:px-6">
            <div className="grid [grid-template-columns:repeat(auto-fit,minmax(160px,1fr))] gap-3">
              <div className="min-w-0 rounded-[20px] border border-[#edf2f7] bg-white px-4 py-4">
                <p className="text-[12px] font-bold text-[#7f8b99]">순 입금액</p>
                <p className="currency-fit mt-2 text-[1rem] font-black tracking-[-0.03em] lg:text-[clamp(0.8rem,1.05vw,1rem)] text-[#191f28]">{formatCompactCurrency(summary.totalOnRampNet, displayCurrency)}</p>
              </div>
              <div className="min-w-0 rounded-[20px] border border-[#edf2f7] bg-white px-4 py-4">
                <p className="text-[12px] font-bold text-[#7f8b99]">총 입금액</p>
                <p className="currency-fit mt-2 text-[1rem] font-black tracking-[-0.03em] lg:text-[clamp(0.8rem,1.05vw,1rem)] text-[#191f28]">{formatCompactCurrency(summary.totalOnRampGross, displayCurrency)}</p>
              </div>
              <div className="min-w-0 rounded-[20px] border border-[#edf2f7] bg-white px-4 py-4">
                <p className="text-[12px] font-bold text-[#7f8b99]">매수 체결 수</p>
                <p className="currency-fit mt-2 text-[1.1rem] font-black text-[#191f28] lg:text-[clamp(0.95rem,1.8vw,1.25rem)]">{buyCount.toLocaleString()}건</p>
              </div>
              <div className="min-w-0 rounded-[20px] border border-[#edf2f7] bg-white px-4 py-4">
                <p className="text-[12px] font-bold text-[#7f8b99]">활성 거래소</p>
                <p className="currency-fit mt-2 text-[1.1rem] font-black text-[#191f28] lg:text-[clamp(0.95rem,1.8vw,1.25rem)]">{activeExchangeCount}곳</p>
                <p className="mt-1 text-[12px] font-bold text-[#7f8b99]">국내외 거래 포함</p>
              </div>
            </div>
          </div>
        </div>
      </SurfaceCard>

      <div className="grid gap-4">
        <div className="rounded-[20px] border border-[#e5e8eb] bg-white px-4 py-4 shadow-[0_10px_24px_rgba(15,23,42,0.04)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[12px] font-black tracking-[0.14em] text-[#8b95a1]">MARKET</p>
              <p className="mt-1 text-[15px] font-black text-[#191f28]">주요 가상자산 시세</p>
            </div>
            <div className="self-start rounded-full bg-[#e7ecf2] p-1">
              <button
                onClick={() => setDisplayCurrency('KRW')}
                className={`rounded-full px-4 py-1.5 text-[12px] font-black transition-all ${displayCurrency === 'KRW' ? 'bg-white text-[#2272eb] shadow-sm' : 'text-[#7f8b99]'}`}
              >
                KRW
              </button>
              <button
                onClick={() => setDisplayCurrency('USD')}
                className={`rounded-full px-4 py-1.5 text-[12px] font-black transition-all ${displayCurrency === 'USD' ? 'bg-white text-[#2272eb] shadow-sm' : 'text-[#7f8b99]'}`}
              >
                USD
              </button>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
            {marketData.map((item) => (
              <div key={item.label} className="min-w-0 rounded-[16px] border border-[#edf2f7] bg-[#f8fafc] px-4 py-4">
                <div className="grid min-w-0 gap-2">
                  <p className="text-[14px] font-black tracking-tight text-[#191f28] sm:text-[15px]">{item.label}</p>
                  <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-2">
                    <p className="currency-fit text-[0.88rem] font-black tracking-[-0.045em] text-[#191f28] sm:text-[0.92rem] lg:text-[0.98rem]">
                      {formatCompactCurrency(item.value, displayCurrency)}
                    </p>
                    <p className={`shrink-0 text-[11px] font-black sm:text-[12px] ${item.pos ? 'text-[#ff5c39]' : 'text-[#2272eb]'}`}>
                      {item.pos ? '+' : ''}
                      {item.change}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.95fr)]">
        <SurfaceCard className="p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[12px] font-black tracking-[0.16em] text-[#8b95a1]">P&L TREND</p>
              <h3 className="mt-2 text-[22px] font-black text-[#191f28]">수익 현황</h3>
            </div>
            <div className="rounded-full bg-[#eef2f6] p-1">
              {(['일', '주', '월', '년'] as TimeFrame[]).map((tf) => (
                <button
                  key={tf}
                  onClick={() => setTimeFrame(tf)}
                  className={`rounded-full px-4 py-1.5 text-[12px] font-black transition-all ${timeFrame === tf ? 'bg-white text-[#2272eb] shadow-sm' : 'text-[#8b95a1]'}`}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-6 h-[220px] w-full md:h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ bottom: 8, left: 4, right: 8, top: 6 }}>
                <defs>
                  <linearGradient id="coinmoaArea" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#3182f7" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="#3182f7" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="#edf2f7" strokeDasharray="4 4" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#97a3b4', fontSize: 11, fontWeight: 700 }} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#97a3b4', fontSize: 11, fontWeight: 700 }} tickFormatter={formatYAxis} width={64} />
                <Tooltip
                  contentStyle={{
                    borderRadius: '18px',
                    border: '1px solid rgba(222,231,241,0.9)',
                    boxShadow: '0 18px 34px rgba(15,23,42,0.10)',
                    fontSize: '13px',
                    fontWeight: '700',
                  }}
                  formatter={(value) => formatCompactCurrency(value as number, displayCurrency)}
                />
                <Area type="monotone" dataKey="pnl" stroke="#2272eb" strokeWidth={3} fill="url(#coinmoaArea)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </SurfaceCard>

        <SurfaceCard className="relative overflow-hidden p-5">
          <div className="absolute right-0 top-0 h-28 w-28 rounded-full bg-[radial-gradient(circle,_rgba(49,130,247,0.18)_0%,_rgba(49,130,247,0)_68%)]" />
          <div className="relative">
            <div className="flex items-center gap-2 text-[#2272eb]">
              <Sparkles size={16} />
              <p className="text-[12px] font-black tracking-[0.16em]">AI MEMO</p>
            </div>
            <h3 className="mt-3 text-[22px] font-black text-[#191f28]">절세 인사이트</h3>
            <div className="mt-5 space-y-3">
              {insightLines.map((line, index) => (
                <div key={`${line}-${index}`} className="rounded-[20px] bg-[#f8fafc] px-4 py-4">
                  <p className="text-[13px] font-bold text-[#4e5a68] leading-relaxed">{line}</p>
                </div>
              ))}
            </div>
          </div>
        </SurfaceCard>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SurfaceCard className="flex flex-col p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[12px] font-black tracking-[0.16em] text-[#8b95a1]">PORTFOLIO MIX</p>
              <h3 className="mt-2 text-[22px] font-black text-[#191f28]">내 자산 구성</h3>
            </div>
            <div className="rounded-[14px] bg-[#eef2f6] p-1">
              <button onClick={() => setBreakdownView('list')} className={`rounded-[10px] p-2 ${breakdownView === 'list' ? 'bg-white text-[#2272eb] shadow-sm' : 'text-[#8b95a1]'}`}><LayoutList size={18} /></button>
              <button onClick={() => setBreakdownView('chart')} className={`rounded-[10px] p-2 ${breakdownView === 'chart' ? 'bg-white text-[#2272eb] shadow-sm' : 'text-[#8b95a1]'}`}><PieChartIcon size={18} /></button>
            </div>
          </div>

          <div className="mt-7 flex-1">
            {breakdownView === 'list' ? (
              <div className="space-y-3">
                <div className={`${isAssetExpanded ? 'max-h-[380px] overflow-y-auto pr-1 custom-scrollbar' : ''} space-y-3`}>
                  {displayedAssets.map((asset, index) => (
                    <div key={asset.symbol} className="flex items-center justify-between rounded-[20px] bg-[#f8fafc] px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <AssetSymbolIcon symbol={asset.symbol} imageUrl={getAssetImageUrl(assetCatalog, asset.symbol)} />
                        <div className="min-w-0">
                          <p className="text-[15px] font-black text-[#191f28]">{asset.symbol}</p>
                          <p className="truncate text-[12px] font-bold text-[#8b95a1]">{getAssetDisplayName(assetCatalog, asset.symbol)}</p>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5">
                            <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-black tracking-[0.04em] text-[#5b6675]">
                              {getAssetSourceLabel(assetCatalog, asset.symbol)}
                            </span>
                            {getAssetRankLabel(assetCatalog, asset.symbol) && (
                              <span className="rounded-full bg-[#eaf1ff] px-2 py-0.5 text-[10px] font-black tracking-[0.04em] text-[#2463eb]">
                                {getAssetRankLabel(assetCatalog, asset.symbol)}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-0.5">
                        <div className="flex items-center gap-1.5">
                          <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                          <p className="currency-nowrap text-[16px] font-black text-[#191f28]">{formatCompactCurrency(asset.currentValue, displayCurrency)}</p>
                        </div>
                        <p className="text-[11px] font-black text-[#8b95a1]">
                          {summary.totalBalanceKRW ? ((asset.currentValue / summary.totalBalanceKRW) * 100).toFixed(2) : '0.00'}%
                        </p>
                      </div>
                    </div>
                  ))}
                </div>

                {assetBreakdown.length > 5 && (
                  <button
                    onClick={() => setIsAssetExpanded(!isAssetExpanded)}
                    className="mt-3 flex w-full items-center justify-center gap-2 rounded-[18px] bg-[#f3f6f9] py-3 text-[14px] font-black text-[#4f5b6a] transition hover:bg-[#edf2f7]"
                  >
                    <span>{isAssetExpanded ? '접기' : `외 ${assetBreakdown.length - 5}개 더 보기`}</span>
                    {isAssetExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                  </button>
                )}
              </div>
            ) : (
              <div className="grid h-full gap-4 md:grid-cols-[minmax(0,1fr)_170px]">
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={assetBreakdown} cx="50%" cy="50%" innerRadius={62} outerRadius={96} paddingAngle={4} dataKey="currentValue" stroke="none">
                        {assetBreakdown.map((_, index) => <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />)}
                      </Pie>
                      <Tooltip
                        cursor={{ fill: 'transparent' }}
                        contentStyle={{
                          borderRadius: '18px',
                          border: '1px solid rgba(222,231,241,0.9)',
                          boxShadow: '0 18px 34px rgba(15,23,42,0.10)',
                        }}
                        formatter={(value) => formatCompactCurrency(value as number, displayCurrency)}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-3">
                  {assetBreakdown.slice(0, 5).map((asset, index) => (
                    <div key={asset.symbol} className="flex items-center justify-between rounded-[18px] bg-[#f8fafc] px-3 py-3">
                      <div className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                        <span className="text-[13px] font-black text-[#4f5b6a]">{asset.symbol}</span>
                      </div>
                      <span className="text-[12px] font-black text-[#191f28]">
                        {summary.totalBalanceKRW ? ((asset.currentValue / summary.totalBalanceKRW) * 100).toFixed(2) : '0.00'}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </SurfaceCard>

        <SurfaceCard>
          <div>
            <p className="text-[12px] font-black tracking-[0.16em] text-[#8b95a1]">EXCHANGE EXPOSURE</p>
            <h3 className="mt-2 text-[22px] font-black text-[#191f28]">거래소 분포</h3>
          </div>
          <div className="mt-7 space-y-5">
            {exchangeBreakdown.map((exchange, index) => (
              <div key={exchange.name} className="space-y-2">
                <div className="flex items-end justify-between">
                  <div>
                    <p className="text-[14px] font-black text-[#191f28]">{getExchangeLabel(exchange.name)}</p>
                    <p className="currency-nowrap text-[12px] font-bold text-[#8b95a1]">{formatCompactCurrency(exchange.value, displayCurrency)}</p>
                  </div>
                  <span className="text-[16px] font-black text-[#191f28]">{exchange.share}%</span>
                </div>
                <div className="h-3 overflow-hidden rounded-full bg-[#eef2f6]">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${exchange.share}%`,
                      background: `linear-gradient(90deg, ${COLORS[index % COLORS.length]} 0%, ${COLORS[(index + 1) % COLORS.length]} 100%)`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="mt-10 rounded-[24px] bg-[linear-gradient(135deg,#f8fbff_0%,#eef5ff_100%)] p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[12px] font-black tracking-[0.16em] text-[#8b95a1]">FOCUS</p>
                <p className="mt-2 text-[18px] font-black text-[#191f28]">{exchangeBreakdown[0] ? getExchangeLabel(exchangeBreakdown[0].name) : '데이터 없음'}</p>
                <p className="mt-1 text-[13px] font-medium leading-relaxed text-[#627487]">
                  현재 mock 데이터 기준으로 거래 흐름이 가장 많이 집중된 거래소입니다.
                </p>
              </div>
              <div className="rounded-full bg-white p-3 shadow-sm">
                <ArrowUpRight className="text-[#2272eb]" size={18} />
              </div>
            </div>
          </div>
        </SurfaceCard>
      </div>
    </div>
  );
};

export default Dashboard;
