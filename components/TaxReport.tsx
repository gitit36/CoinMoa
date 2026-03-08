import React, { useMemo } from 'react';
import { Download, Printer, Info, Calculator, ShieldAlert, Sparkles, ReceiptText } from 'lucide-react';
import { Transaction, PortfolioSummary } from '../types.ts';

interface TaxReportProps {
  transactions: Transaction[];
  summary: PortfolioSummary;
}

const TaxReport: React.FC<TaxReportProps> = ({ summary }) => {
  const formatKRW = (val: number) => `${Math.round(val).toLocaleString('ko-KR')}원`;
  const statCards = [
    { label: '실현 손익', value: formatKRW(summary.pnlAmount), tone: summary.pnlAmount >= 0 ? 'text-[#ff5c39]' : 'text-[#2272eb]' },
    { label: '기본 공제액', value: formatKRW(2500000), tone: 'text-[#191f28]' },
  ];

  const taxCalculation = useMemo(() => {
    const baseDeduction = 2500000; // 250만원 기본 공제
    const taxableIncome = Math.max(0, summary.pnlAmount - baseDeduction);
    const estimatedTax = taxableIncome * 0.22; // 소득세 20% + 지방세 2%
    
    return {
      baseDeduction,
      taxableIncome,
      estimatedTax,
      isExempt: summary.pnlAmount <= baseDeduction
    };
  }, [summary.pnlAmount]);

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-6 duration-700">
      <div className="overflow-hidden rounded-[32px] border border-white/70 bg-white/92 shadow-[0_18px_48px_rgba(25,31,40,0.06)] backdrop-blur">
        <div className="bg-[linear-gradient(135deg,#16202c_0%,#243244_52%,#354759_100%)] px-8 py-8 text-white md:px-10">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/6 px-3 py-1 text-[11px] font-black tracking-[0.2em] text-white/76">
                <ReceiptText size={12} />
                TAX PREVIEW
              </div>
              <h3 className="mt-4 text-[30px] font-black tracking-tight md:text-[36px]">가상자산 세무 시뮬레이션</h3>
              <p className="mt-2 max-w-2xl text-[14px] font-medium leading-relaxed text-white/78">
                2025년 과세안 기준으로 예상 과세 범위를 빠르게 읽을 수 있는 미리보기 화면입니다. 실제 신고 전에 필요한 공제와 제출 리스크를 한 장에서 확인합니다.
              </p>
            </div>
            <div className="flex w-full gap-2 md:w-auto">
              <button className="flex flex-1 items-center justify-center gap-2 rounded-[16px] border border-white/20 bg-white/10 px-5 py-3 text-sm font-bold text-white backdrop-blur transition-all hover:bg-white/16 md:flex-none">
                <Printer size={18} />
                <span>인쇄</span>
              </button>
              <button className="flex flex-1 items-center justify-center gap-2 rounded-[16px] bg-white px-5 py-3 text-sm font-black text-[#2272eb] shadow-sm transition-all hover:brightness-95 md:flex-none">
                <Download size={18} />
                <span>PDF 저장</span>
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-8 px-8 py-8 md:px-10 md:py-9">
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(260px,0.9fr)]">
            <div className="grid min-w-0 gap-4 sm:grid-cols-2">
              {statCards.map((card) => (
                <div key={card.label} className="min-w-0 rounded-[26px] bg-[#f8fafc] px-5 py-5 sm:px-6 sm:py-6">
                  <p className="text-[12px] font-black tracking-[0.12em] text-[#8b95a1]">{card.label}</p>
                  <p className={`currency-fit mt-3 text-[clamp(1.05rem,1.7vw,1.45rem)] font-black leading-none tracking-[-0.03em] ${card.tone}`}>{card.value}</p>
                </div>
              ))}
            </div>

            <div className="relative min-w-0 overflow-hidden rounded-[28px] border border-[#d9e2ec] bg-[linear-gradient(135deg,#fbfcfe_0%,#f1f5f9_100%)] px-5 py-5 sm:px-6 sm:py-6">
              <div className="absolute right-0 top-0 h-28 w-28 rounded-full bg-[radial-gradient(circle,_rgba(71,85,105,0.12)_0%,_rgba(71,85,105,0)_70%)]" />
              <div className="relative min-w-0">
                <div className="flex items-center gap-2 text-[#334155]">
                  <ShieldAlert size={16} />
                  <p className="text-[12px] font-black tracking-[0.16em]">ESTIMATED TAX</p>
                </div>
                <p className="currency-fit mt-3 text-[clamp(1.15rem,2vw,1.7rem)] font-black leading-none tracking-[-0.035em] text-[#0f172a]">
                  {taxCalculation.isExempt ? '0원' : formatKRW(taxCalculation.estimatedTax)}
                </p>
                <p className="mt-2 text-[13px] font-medium leading-relaxed text-[#627487]">
                  {taxCalculation.isExempt ? '기본 공제 범위 안에 있어 예상 납부 세액이 없습니다.' : '기본 공제 후 남는 과세 표준에 22%를 적용한 단순 추정치입니다.'}
                </p>
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="min-w-0 rounded-[24px] bg-[#f8fafc] px-5 py-5 sm:px-6 sm:py-6">
              <div className="flex items-center justify-between">
                <p className="text-[12px] font-black tracking-[0.14em] text-[#8b95a1]">과세 표준</p>
                <Calculator size={15} className="text-[#adb5bd]" />
              </div>
              <p className="currency-fit mt-3 text-[clamp(1.05rem,1.65vw,1.4rem)] font-black leading-none tracking-[-0.03em] text-[#191f28]">{formatKRW(taxCalculation.taxableIncome)}</p>
              <p className="mt-2 text-[13px] font-medium text-[#6b7684]">공제 후 남는 손익만 반영합니다.</p>
            </div>

            <div className="min-w-0 rounded-[24px] bg-[#f8fafc] px-5 py-5 sm:px-6 sm:py-6">
              <div className="flex items-center gap-2 text-[#2272eb]">
                <Sparkles size={15} />
                <p className="text-[12px] font-black tracking-[0.14em]">CHECKPOINT</p>
              </div>
              <p className="mt-3 text-[18px] font-black text-[#191f28]">
                {taxCalculation.isExempt ? '지금은 신고 부담이 낮은 구간입니다.' : '거래별 취득가 증빙 정리가 필요합니다.'}
              </p>
              <p className="mt-2 text-[13px] font-medium leading-relaxed text-[#6b7684]">
                단일 수치보다 매수 원가, 송금 이동, 거래소별 내역 정합성이 실제 신고 품질을 좌우합니다.
              </p>
            </div>

            <div className="min-w-0 rounded-[24px] bg-[#191f28] px-5 py-5 text-white sm:px-6 sm:py-6">
              <p className="text-[12px] font-black tracking-[0.14em] text-white/62">STATUS</p>
              <p className="mt-3 text-[22px] font-black">
                {taxCalculation.isExempt ? '공제 범위 내' : '과세 가능성 있음'}
              </p>
              <p className="mt-2 text-[13px] font-medium leading-relaxed text-white/72">
                이 화면은 세무사 검토 전 내부 점검용 UI입니다.
              </p>
            </div>
          </div>

          <div className="min-w-0 rounded-[24px] bg-[#f3f6f9] px-5 py-5 sm:px-6">
            <div className="flex items-start gap-3">
              <Info className="mt-0.5 shrink-0 text-[#8b95a1]" size={18} />
              <div className="text-[13px] font-medium leading-relaxed text-[#4e5968]">
                <p className="mb-1 font-black text-[#191f28]">알림</p>
                <p>
                  위 계산은 2025년 시행 예정인 가상자산 과세안을 바탕으로 한 시뮬레이션입니다. 실제 세액은 거래 방식, 손익 귀속 시점, 증빙 자료 정리 상태에 따라 달라질 수 있습니다.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TaxReport;
