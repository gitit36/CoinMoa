import React, { useMemo, useState } from 'react';
import { Search, ArrowUpRight, ArrowDownLeft, Download, Globe, Sparkles, ChevronRight, SlidersHorizontal } from 'lucide-react';
import { Transaction, TransactionType, ExchangeName } from '../types.ts';
import { AssetCatalog, getAssetDisplayName, getAssetSearchAliases, getExchangeLabel, getExchangeSearchAliases, getPairSubtitle } from '../services/marketMeta.ts';

interface TransactionTableProps {
  transactions: Transaction[];
  assetCatalog: AssetCatalog;
}

const TransactionTable: React.FC<TransactionTableProps> = ({ transactions, assetCatalog }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedType, setSelectedType] = useState<'ALL' | TransactionType>('ALL');

  const filtered = useMemo(() => (
    transactions.filter((t) => {
      const searchIndex = [
        t.pair,
        t.exchange,
        t.currency,
        getExchangeLabel(String(t.exchange)),
        getAssetDisplayName(assetCatalog, t.currency),
        ...getExchangeSearchAliases(String(t.exchange)),
        ...getAssetSearchAliases(assetCatalog, t.currency),
      ].join(' ').toLowerCase();
      const matchesSearch =
        searchIndex.includes(searchTerm.toLowerCase());

      const matchesType = selectedType === 'ALL' || t.type === selectedType;
      return matchesSearch && matchesType;
    })
  ), [searchTerm, selectedType, transactions]);

  const formatKRW = (val: number) => Math.round(val).toLocaleString() + '원';
  const formatUSD = (val: number) => val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  const formatCompactKRW = (val: number) => {
    const abs = Math.abs(val);
    if (abs >= 100000000) return `${(val / 100000000).toFixed(1)}억원`;
    if (abs >= 10000) return `${Math.round(val / 10000).toLocaleString()}만원`;
    return formatKRW(val);
  };
  const totalValue = filtered.reduce((sum, tx) => sum + Math.abs(tx.krwValue), 0);
  const overseasCount = filtered.filter((tx) => tx.exchangeRate).length;
  const typeOptions: Array<'ALL' | TransactionType> = ['ALL', 'DEPOSIT', 'BUY', 'SELL', 'WITHDRAWAL', 'LIQUIDATION'];

  const getIcon = (type: TransactionType) => {
    switch (type) {
      case 'DEPOSIT': return <ArrowDownLeft className="text-[#3182f7]" size={16} />;
      case 'WITHDRAWAL': return <ArrowUpRight className="text-[#f04452]" size={16} />;
      case 'BUY': return <div className="w-1.5 h-1.5 rounded-full bg-[#3182f7]" />;
      case 'SELL': return <div className="w-1.5 h-1.5 rounded-full bg-[#f04452]" />;
      case 'LIQUIDATION': return <div className="w-2 h-2 rounded-full bg-[#191f28]" />;
      default: return null;
    }
  };

  const getTypeLabel = (type: 'ALL' | TransactionType) => {
    switch (type) {
      case 'ALL': return '전체';
      case 'DEPOSIT': return '입금';
      case 'WITHDRAWAL': return '출금';
      case 'BUY': return '매수';
      case 'SELL': return '매도';
      case 'LIQUIDATION': return '청산';
      default: return type;
    }
  };

  const handleDownloadCSV = () => {
    if (filtered.length === 0) return;

    // CSV 헤더 설정
    const headers = ["날짜", "거래소", "유형", "페어", "수량", "통화", "가격", "원화가치(KRW)", "적용환율"];
    
    // 데이터 행 생성 (숫자에 콤마 추가 및 큰따옴표 처리)
    const rows = filtered.map(tx => {
      const row = [
        new Date(tx.timestamp).toLocaleString('ko-KR'),
        tx.exchange,
        tx.type,
        tx.pair,
        tx.amount.toLocaleString(undefined, { maximumFractionDigits: 8 }), // 수량 콤마
        tx.currency,
        tx.price.toLocaleString(undefined, { maximumFractionDigits: 2 }), // 가격 콤마
        Math.round(tx.krwValue).toLocaleString(), // 원화가치 콤마
        tx.exchangeRate ? Math.round(tx.exchangeRate).toLocaleString() : "" // 환율 콤마
      ];
      // 각 셀을 큰따옴표로 감싸서 콤마가 포함되어도 셀이 밀리지 않게 함
      return row.map(cell => `"${cell.replace(/"/g, '""')}"`).join(",");
    });

    // CSV 문자열 합치기 (헤더도 따옴표 처리)
    const headerRow = headers.map(h => `"${h}"`).join(",");
    const csvContent = [headerRow, ...rows].join("\n");
    
    // 한글 깨짐 방지를 위한 BOM(Byte Order Mark) 추가
    const BOM = "\uFEFF";
    const blob = new Blob([BOM + csvContent], { type: "text/csv;charset=utf-8;" });
    
    // 다운로드 링크 생성 및 클릭
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const dateStr = new Date().toISOString().split('T')[0];
    link.setAttribute("href", url);
    link.setAttribute("download", `k-crypto-transactions-${dateStr}.csv`);
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="surface-card overflow-hidden rounded-[32px]">
        <div className="bg-[linear-gradient(135deg,#16202c_0%,#243244_52%,#354759_100%)] px-8 py-8 text-white">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/6 px-3 py-1 text-[11px] font-black tracking-[0.2em] text-white/76">
                <Sparkles size={12} />
                TRANSACTION FEED
              </div>
              <h3 className="mt-4 text-[30px] font-black tracking-tight md:text-[36px]">전체 거래 내역</h3>
              <p className="mt-2 max-w-2xl text-[14px] font-medium leading-relaxed text-white/78">
                거래소, 자산, 입출금 흐름을 한 화면에서 빠르게 훑을 수 있게 정리한 타임라인입니다. 지금은 mock 데이터 기준으로 시각적 구조만 다듬은 상태입니다.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 text-[#dfeaff] md:min-w-[360px]">
              <div className="rounded-[22px] bg-white/10 px-4 py-4 backdrop-blur">
                <p className="text-[12px] font-bold text-white/62">표시 건수</p>
                <p className="currency-nowrap mt-2 text-[22px] font-black text-white">{filtered.length.toLocaleString()}건</p>
                <p className="mt-1 text-[12px] font-bold text-white/62">현재 필터 기준</p>
              </div>
              <div className="rounded-[22px] bg-white/10 px-4 py-4 backdrop-blur">
                <p className="text-[12px] font-bold text-white/62">누적 흐름</p>
                <p className="mt-2 whitespace-nowrap text-[18px] font-black text-white md:text-[22px]">{formatCompactKRW(totalValue)}</p>
                <p className="mt-1 text-[12px] font-bold text-white/62">절대값 합계</p>
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-4 bg-white px-6 py-4 md:grid-cols-2 md:px-8">
          <div className="rounded-[20px] bg-[#f8fafc] px-5 py-4">
            <p className="text-[12px] font-black tracking-[0.12em] text-[#8b95a1]">필터 상태</p>
            <p className="currency-nowrap mt-2 text-[20px] font-black text-[#191f28]">{getTypeLabel(selectedType)}</p>
            <p className="mt-1 text-[12px] font-bold text-[#8b95a1]">거래 유형 기준</p>
          </div>
          <div className="rounded-[20px] bg-[#f8fafc] px-5 py-4">
            <p className="text-[12px] font-black tracking-[0.12em] text-[#8b95a1]">해외 거래</p>
            <p className="currency-nowrap mt-2 text-[20px] font-black text-[#191f28]">{overseasCount.toLocaleString()}건</p>
            <p className="mt-1 text-[12px] font-bold text-[#8b95a1]">환율 정보 포함</p>
          </div>
        </div>
      </div>

      <div className="surface-card rounded-[32px] p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="pill-label">
              <SlidersHorizontal size={12} />
              LIVE FILTER
            </div>
            <p className="mt-3 text-[22px] font-black text-[#191f28]">원하는 거래만 빠르게 좁혀보기</p>
          </div>
          <div className="flex w-full flex-col gap-3 lg:w-auto lg:flex-row lg:items-center">
            <div className="relative w-full lg:w-64">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-[#adb5bd]" size={16} />
              <input 
                type="text" 
                placeholder="자산, 거래소 검색"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full rounded-[16px] border-none bg-[#f2f4f6] py-3 pl-11 pr-4 text-sm font-medium outline-none transition-all focus:ring-2 focus:ring-[#3182f7]"
              />
            </div>
            <div className="flex items-center gap-2 overflow-x-auto whitespace-nowrap pb-1 custom-scrollbar">
              {typeOptions.map((type) => (
                <button
                  key={type}
                  onClick={() => setSelectedType(type)}
                  className={`shrink-0 rounded-full px-3 py-2 text-[12px] font-black transition-all ${
                    selectedType === type ? 'bg-[#191f28] text-white shadow-sm' : 'bg-[#f2f4f6] text-[#6b7684]'
                  }`}
                >
                  {getTypeLabel(type)}
                </button>
              ))}
            </div>
            <button 
              onClick={handleDownloadCSV}
              className="flex shrink-0 items-center justify-center space-x-2 rounded-[16px] bg-[#f2f4f6] px-5 py-3 text-sm font-bold text-[#4e5968] transition-all hover:brightness-95 active:scale-95"
            >
              <Download size={16} />
              <span>CSV 다운로드</span>
            </button>
          </div>
        </div>

        <div className="mt-6 max-h-[70vh] overflow-y-auto pr-1 custom-scrollbar md:max-h-[640px]">
          <div className="space-y-3">
            {filtered.map((tx) => (
              <div key={tx.id} className="surface-muted group rounded-[22px] px-4 py-3 transition-colors hover:bg-white">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex items-center space-x-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[16px] bg-white transition-colors group-hover:bg-[#f5f9ff]">
                    {getIcon(tx.type)}
                    </div>
                    <div className="min-w-0">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <div className="min-w-0">
                          <p className="text-[15px] font-black text-[#191f28]">{tx.pair}</p>
                          <p className="truncate text-[11px] font-bold text-[#8b95a1]">
                            {getPairSubtitle(assetCatalog, tx.pair, String(tx.exchange))}
                          </p>
                        </div>
                        <span className={`rounded-full px-2.5 py-1 text-[10px] font-black ${
                          tx.exchange === ExchangeName.BINANCE 
                            ? 'bg-[#191f28] text-[#f3ba2f]' 
                            : 'bg-white text-[#8b95a1]'
                        }`}>
                        {getExchangeLabel(String(tx.exchange))}
                        </span>
                        <span className="rounded-full bg-[#eef5ff] px-2.5 py-1 text-[10px] font-black text-[#2272eb]">
                          {getTypeLabel(tx.type)}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-[12px] font-medium text-[#adb5bd]">{new Date(tx.timestamp).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</p>
                        <span className="truncate text-[12px] font-bold text-[#8b95a1]">{getAssetDisplayName(assetCatalog, tx.currency)}</span>
                      {tx.exchangeRate && (
                        <div className="flex items-center rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-bold text-[#3182f7]">
                          <Globe size={10} className="mr-1" />
                          환율 {Math.round(tx.exchangeRate).toLocaleString()}원
                        </div>
                      )}
                    </div>
                  </div>
                </div>
                
                  <div className="flex items-center justify-between gap-4 lg:justify-end">
                    <div className="lg:hidden">
                      <ChevronRight size={18} className="text-[#b1bac5]" />
                    </div>
                    <div className="text-right shrink-0">
                      <p className={`currency-nowrap text-[16px] font-black ${
                        tx.type === 'SELL' || tx.type === 'WITHDRAWAL' || tx.type === 'LIQUIDATION' ? 'text-[#191f28]' : 'text-[#3182f7]'
                      }`}>
                        {tx.type === 'SELL' || tx.type === 'WITHDRAWAL' || tx.type === 'LIQUIDATION' ? '-' : '+'}{formatKRW(tx.krwValue)}
                      </p>
                      <div className="mt-1 flex flex-col items-end">
                        <p className="currency-nowrap text-[12px] font-bold text-[#8b95a1]">
                          {tx.amount.toFixed(assetDecimal(tx.currency))} {tx.currency}
                        </p>
                        {tx.exchange === ExchangeName.BINANCE && (
                          <p className="text-[10px] font-medium text-[#adb5bd]">
                            (@ ${formatUSD(tx.price)})
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
            
            {filtered.length === 0 && (
              <div className="surface-muted rounded-[24px] py-20 text-center">
                <p className="text-[18px] font-black text-[#191f28]">검색 결과가 없습니다.</p>
                <p className="mt-2 text-[13px] font-medium text-[#8b95a1]">검색어나 거래 유형 필터를 바꿔 다시 확인하세요.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// 자산별 적절한 소수점 표시를 위한 헬퍼
function assetDecimal(symbol: string): number {
  if (symbol === 'BTC' || symbol === 'ETH') return 4;
  if (symbol === 'KRW') return 0;
  return 2;
}

export default TransactionTable;
