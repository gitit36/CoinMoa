
/**
 * FORBIDDEN_ENDPOINTS_GUARD:
 * 본 소스코드 및 하위 로직에서는 어떠한 경우에도 매수/매도(Place Order), 
 * 출금(Withdraw), 주문 취소(Cancel Order) API를 호출하지 않습니다.
 * 모든 연결은 READ-ONLY 권한을 전제로 합니다.
 */

import React, { useState, useMemo } from 'react';
import { 
  ShieldCheck, 
  Trash2, 
  Key, 
  Info, 
  AlertTriangle, 
  CheckCircle2, 
  ChevronRight,
  Wallet,
  Lock
} from 'lucide-react';
import { ExchangeAccount, ExchangeName } from '../types.ts';
import { getExchangeLabel } from '../services/marketMeta.ts';

interface ExchangeManagerProps {
  accounts: ExchangeAccount[];
  setAccounts: React.Dispatch<React.SetStateAction<ExchangeAccount[]>>;
}

const ExchangeManager: React.FC<ExchangeManagerProps> = ({ accounts, setAccounts }) => {
  const [selectedExchange, setSelectedExchange] = useState<ExchangeName>(ExchangeName.UPBIT);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [hasAttested, setHasAttested] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 현재 선택된 거래소의 특성에 따른 UI 구성 결정
  const config = useMemo(() => {
    switch (selectedExchange) {
      case ExchangeName.LIGHTER:
        return {
          keyLabel: '읽기 전용 토큰 (Read-only Token)',
          keyPlaceholder: 'ro:로 시작하는 토큰을 입력하세요',
          showSecret: false,
          guide: '라이터는 보안을 위해 "읽기 전용 토큰"만 연결할 수 있습니다. 개인키(Private Key)는 절대 입력하지 마세요.',
          validate: (k: string) => k.startsWith('ro:') ? null : '읽기 전용 토큰은 "ro:"로 시작해야 합니다.'
        };
      case ExchangeName.HYPERLIQUID:
        return {
          keyLabel: '지갑 주소 (Wallet Address)',
          keyPlaceholder: '0x로 시작하는 지갑 주소를 입력하세요',
          showSecret: false,
          guide: '하이퍼리퀴드는 지갑 주소만으로 자산 조회가 가능합니다. API Key나 시크릿은 필요하지 않습니다.',
          validate: (k: string) => k.startsWith('0x') && k.length >= 40 ? null : '유효한 지갑 주소(0x...)를 입력해주세요.'
        };
      case ExchangeName.BINANCE:
        return {
          keyLabel: 'API Key',
          keyPlaceholder: 'Binance API Key 입력',
          showSecret: true,
          guide: '바이낸스 API 생성 시 "Enable Reading"만 체크하고, "Enable Spot & Margin Trading" 및 "Enable Withdrawals"는 반드시 해제하세요.',
          validate: (k: string, s: string) => k && s ? null : 'API Key와 Secret을 모두 입력해주세요.'
        };
      default:
        return {
          keyLabel: 'API Key (Access Key)',
          keyPlaceholder: 'API Key 입력',
          showSecret: true,
          guide: '거래소 설정에서 "조회(View)" 권한만 활성화된 키를 사용하세요. 주문/출금 권한이 포함된 키는 등록이 거절될 수 있습니다.',
          validate: (k: string, s: string) => k && s ? null : 'Key와 Secret을 모두 입력해주세요.'
        };
    }
  }, [selectedExchange]);

  const handleConnect = () => {
    setError(null);
    const validationError = config.validate(apiKey, apiSecret);
    
    if (validationError) {
      setError(validationError);
      return;
    }

    if (config.showSecret && !hasAttested) {
      setError('읽기 전용 권한 확인 문구에 동의해주세요.');
      return;
    }

    setAccounts(prev => prev.map(acc => 
      acc.name === selectedExchange 
        ? { ...acc, apiKey: apiKey, apiSecret: apiSecret, connected: true, lastSyncedAt: Date.now() } 
        : acc
    ));

    setApiKey('');
    setApiSecret('');
    setHasAttested(false);
    setError(null);
  };

  const handleDisconnect = (name: ExchangeName) => {
    if (confirm(`${name} 연결을 해제하시겠습니까?`)) {
      setAccounts(prev => prev.map(acc => 
        acc.name === name ? { ...acc, apiKey: '', apiSecret: '', connected: false } : acc
      ));
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500 pb-10">
      <div className="overflow-hidden rounded-[32px] border border-white/70 bg-white/92 shadow-[0_18px_48px_rgba(25,31,40,0.06)] backdrop-blur">
        <div className="bg-[linear-gradient(135deg,#16202c_0%,#243244_52%,#354759_100%)] px-8 py-8 text-white">
          <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/6 px-3 py-1 text-[11px] font-black tracking-[0.2em] text-white/76">
                <ShieldCheck size={12} />
                READ-ONLY POLICY
              </div>
              <h3 className="mt-4 text-[30px] font-black tracking-tight md:text-[34px]">조회 전용 연결만 지원</h3>
              <p className="mt-2 max-w-2xl text-[14px] font-medium leading-relaxed text-white/78">
                이 프로토타입은 주문, 매수, 매도, 출금을 다루지 않습니다. 자산 분석을 위해 조회 권한만 있는 키나 주소만 입력하는 흐름으로 UI를 설계했습니다.
              </p>
            </div>
            <div className="rounded-[22px] bg-white/10 px-5 py-4 backdrop-blur">
              <p className="text-[12px] font-black text-white/62">현재 연결</p>
              <p className="currency-nowrap mt-2 text-[24px] font-black text-white">{accounts.filter(a => a.connected).length}개</p>
              <p className="mt-1 text-[12px] font-bold text-white/62">읽기 전용 기준</p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-2 lg:px-8 lg:py-8">
          <div className="rounded-[28px] bg-[#fbfcfe] px-6 py-6">
            <div className="mb-6 flex items-center justify-between">
              <h3 className="text-[20px] font-black text-[#191f28]">연결된 계정</h3>
              <span className="rounded-full bg-white px-3 py-1 text-[11px] font-black text-[#7f8b99] shadow-sm">
                {accounts.filter(a => a.connected).length}개 연결됨
              </span>
            </div>
            
            <div className="space-y-4">
              {accounts.map((acc) => (
                <div 
                  key={acc.name} 
                  className={`flex items-center justify-between rounded-[24px] border px-4 py-4 transition-all ${
                    acc.connected ? 'border-[#dce8fb] bg-[linear-gradient(135deg,#f8fbff_0%,#eef5ff_100%)]' : 'border-[#edf2f7] bg-white'
                  }`}
                >
                  <div className="flex items-center space-x-4">
                    <div className={`flex h-12 w-12 items-center justify-center rounded-[16px] font-black uppercase text-sm ${
                      acc.connected ? 'bg-[#2272eb] text-white shadow-[0_10px_20px_rgba(34,114,235,0.18)]' : 'bg-[#eef2f6] text-[#8b95a1]'
                    }`}>
                      {acc.name[0]}
                    </div>
                    <div>
                      <h4 className="flex items-center font-black text-[#191f28]">
                      {getExchangeLabel(acc.name)}
                        {acc.connected && <CheckCircle2 size={14} className="ml-1.5 text-[#2272eb]" />}
                      </h4>
                      <p className={`text-xs font-bold ${acc.connected ? 'text-[#2272eb]' : 'text-[#8b95a1]'}`}>
                        {acc.connected ? '데이터 조회 중' : '연결 정보 없음'}
                      </p>
                    </div>
                  </div>
                  {acc.connected ? (
                    <button 
                      onClick={() => handleDisconnect(acc.name)} 
                      className="rounded-full p-2 text-[#8b95a1] transition-all hover:bg-red-50 hover:text-[#f04452]"
                    >
                      <Trash2 size={20} />
                    </button>
                  ) : (
                    <button 
                      onClick={() => setSelectedExchange(acc.name)} 
                      className="rounded-full p-2 text-[#8b95a1] transition-all hover:bg-blue-50 hover:text-[#2272eb]"
                    >
                      <ChevronRight size={24} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[28px] bg-white px-6 py-6 shadow-[inset_0_0_0_1px_rgba(229,232,235,0.8)]">
            <h3 className="flex items-center text-[20px] font-black text-[#191f28]">
              <Lock className="mr-2 text-[#2272eb]" size={20} />
              보안 연결 추가
            </h3>
            
            <div className="mt-6 space-y-6">
              <div className="space-y-3">
                <p className="text-[12px] font-black tracking-[0.14em] text-[#8b95a1]">EXCHANGE</p>
                <div className="flex flex-wrap gap-2">
                  {[
                    ExchangeName.UPBIT, 
                    ExchangeName.BITHUMB, 
                    ExchangeName.BINANCE, 
                    ExchangeName.LIGHTER, 
                    ExchangeName.HYPERLIQUID
                  ].map(name => (
                    <button
                      key={name}
                      onClick={() => {
                        setSelectedExchange(name);
                        setApiKey('');
                        setApiSecret('');
                        setHasAttested(false);
                        setError(null);
                      }}
                      className={`rounded-[14px] border px-4 py-2.5 text-xs font-black transition-all ${
                        selectedExchange === name 
                          ? 'border-[#191f28] bg-[#191f28] text-white shadow-md' 
                          : 'border-transparent bg-[#f2f4f6] text-[#4e5968] hover:border-[#d2dae3]'
                      }`}
                    >
                      {getExchangeLabel(name)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-start space-x-3 rounded-[22px] border border-[#edf2f7] bg-[#f8fafc] p-4">
                <Info className="mt-0.5 shrink-0 text-[#2272eb]" size={16} />
                <p className="text-[13px] font-medium leading-normal text-[#4e5968]">{config.guide}</p>
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="ml-1 text-[13px] font-black text-[#4e5968]">{config.keyLabel}</label>
                  <div className="relative">
                    <Key className="absolute left-4 top-1/2 -translate-y-1/2 text-[#adb5bd]" size={18} />
                    <input 
                      type="text" 
                      value={apiKey} 
                      onChange={e => setApiKey(e.target.value)}
                      placeholder={config.keyPlaceholder}
                      className="w-full rounded-[18px] border-none bg-[#f2f4f6] py-4 pl-12 pr-5 text-sm font-medium outline-none transition-all focus:ring-2 focus:ring-[#3182f7]"
                    />
                  </div>
                </div>

                {config.showSecret && (
                  <div className="space-y-1.5">
                    <label className="ml-1 text-[13px] font-black text-[#4e5968]">API Secret / Private Key</label>
                    <div className="relative">
                      <Lock className="absolute left-4 top-1/2 -translate-y-1/2 text-[#adb5bd]" size={18} />
                      <input 
                        type="password" 
                        value={apiSecret} 
                        onChange={e => setApiSecret(e.target.value)}
                        placeholder="Secret Key 입력"
                        className="w-full rounded-[18px] border-none bg-[#f2f4f6] py-4 pl-12 pr-5 text-sm font-medium outline-none transition-all focus:ring-2 focus:ring-[#3182f7]"
                      />
                    </div>
                  </div>
                )}

                {config.showSecret && (
                  <label className="group flex cursor-pointer items-start space-x-3 rounded-[18px] bg-[#f8fafc] p-3">
                    <input 
                      type="checkbox" 
                      checked={hasAttested}
                      onChange={e => setHasAttested(e.target.checked)}
                      className="mt-1 h-4 w-4 rounded border-gray-300 text-[#3182f7] focus:ring-[#3182f7]"
                    />
                    <span className="text-[12px] font-medium text-[#8b95a1] transition-colors group-hover:text-[#4e5968]">
                      입력한 API 키가 <span className="font-bold text-[#3182f7]">조회 전용(Read-only)</span> 권한으로 생성되었음을 확인하며, 주문 및 출금 권한이 포함되지 않았음을 확약합니다.
                    </span>
                  </label>
                )}
              </div>

              {error && (
                <div className="flex items-center space-x-2 rounded-[18px] border border-red-100 bg-red-50 p-4 text-red-500">
                  <AlertTriangle size={16} />
                  <span className="text-xs font-bold">{error}</span>
                </div>
              )}

              <button 
                onClick={handleConnect}
                disabled={!apiKey || (config.showSecret && !apiSecret)}
                className="w-full rounded-[20px] bg-[#191f28] py-5 text-[16px] font-black text-white shadow-lg shadow-black/5 transition-all hover:brightness-125 disabled:opacity-20 active:scale-95"
              >
                {getExchangeLabel(selectedExchange)} 안전하게 연결하기
              </button>
            </div>
          </div>
        </div>

        <div className="grid gap-4 border-t border-[#eef2f6] px-6 py-6 md:grid-cols-3 lg:px-8">
          <div className="rounded-[22px] bg-[#f8fafc] px-5 py-5">
            <Wallet className="text-[#2272eb]" size={18} />
            <p className="mt-3 text-[16px] font-black text-[#191f28]">거래 권한 차단</p>
            <p className="mt-1 text-[13px] font-medium leading-relaxed text-[#6a7789]">주문, 매도, 출금 UI는 설계 범위 밖으로 둡니다.</p>
          </div>
          <div className="rounded-[22px] bg-[#f8fafc] px-5 py-5">
            <ShieldCheck className="text-[#2272eb]" size={18} />
            <p className="mt-3 text-[16px] font-black text-[#191f28]">권한 인지 확인</p>
            <p className="mt-1 text-[13px] font-medium leading-relaxed text-[#6a7789]">민감한 키는 읽기 전용이라는 사용자의 확인을 거칩니다.</p>
          </div>
          <div className="rounded-[22px] bg-[#f8fafc] px-5 py-5">
            <Info className="text-[#2272eb]" size={18} />
            <p className="mt-3 text-[16px] font-black text-[#191f28]">연결 상태 분리</p>
            <p className="mt-1 text-[13px] font-medium leading-relaxed text-[#6a7789]">거래소 목록과 입력 폼을 분리해 현재 상태를 빠르게 읽게 했습니다.</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExchangeManager;
