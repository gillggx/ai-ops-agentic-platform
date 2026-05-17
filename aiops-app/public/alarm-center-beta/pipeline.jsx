// Deep diagnosis pipeline page — #1940 progress + results
const { useState: useStateDiag, useEffect: useEffectDiag } = React;

const PIPELINE_STEPS = [
  { id: 's1', name: 'Fetch SPC raw data', node: 'patrol-pipeline', duration: '2.3s', status: 'done',
    output: '取得 EQP-03 最近 200 筆 SPC 資料 · 5 個 step type · 12 個 chart' },
  { id: 's2', name: 'Detect OOC pattern', node: 'rule-engine', duration: '0.8s', status: 'done',
    output: '匹配規則 SPC_OOC_RULE_3_OF_5 · 命中 3/5 violations · STEP_007 為主要 step' },
  { id: 's3', name: 'Pull APC parameters', node: 'apc-fetcher', duration: '1.4s', status: 'done',
    output: '取得 LOT-0043 對應 APC run · 28 個 control parameter' },
  { id: 's4', name: 'Compare vs baseline', node: 'baseline-engine', duration: '3.1s', status: 'done',
    output: '2 個參數偏移 > 2σ · etch_rate_pred (+2.4σ) · gas_flow_comp (-1.8σ)' },
  { id: 's5', name: 'Cross-tool correlation', node: 'graph-engine', duration: '4.2s', status: 'done',
    output: '查詢 BAY-A chamber group · EQP-07 同期間 8 件相似 OOC · 關聯度 0.86' },
  { id: 's6', name: 'Root cause inference', node: 'llm-reasoner', duration: '6.8s', status: 'running',
    output: '正在生成診斷敘述... (token 412/1024)' },
  { id: 's7', name: 'Generate action plan', node: 'planner', duration: '—', status: 'pending', output: '' },
  { id: 's8', name: 'Render report', node: 'report-engine', duration: '—', status: 'pending', output: '' },
];

const PipelineRunPage = ({ onBack }) => {
  const [tick, setTick] = useStateDiag(0);
  const [tab, setTab] = useStateDiag('graph');
  useEffectDiag(() => {
    const i = setInterval(() => setTick(t => t + 1), 800);
    return () => clearInterval(i);
  }, []);

  const totalDuration = PIPELINE_STEPS.filter(s => s.status === 'done').reduce((sum, s) => sum + parseFloat(s.duration), 0);
  const doneCount = PIPELINE_STEPS.filter(s => s.status === 'done').length;
  const progress = (doneCount / PIPELINE_STEPS.length) * 100;

  return (
    <div className="detail" style={{ overflow: 'hidden' }}>
      <div className="detail-head">
        <button className="btn icon" onClick={onBack}><Icon name="arrowRight" size={12} /></button>
        <div className="sev-icon" style={{ background: 'var(--accent-bg)', color: 'var(--accent)' }}>
          <Icon name="cpu" size={16} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="detail-title">深度診斷 Pipeline · Run #1940</div>
          <div className="detail-sub">
            觸發來源 <strong>EQP-03 cluster</strong> · 啟動於 14:11:25 · 經過 {totalDuration.toFixed(1)}s · {doneCount}/{PIPELINE_STEPS.length} 步驟完成
          </div>
        </div>
        <div className="detail-actions">
          <button className="btn"><Icon name="pause" size={11} /> 暫停</button>
          <button className="btn"><Icon name="refresh" size={11} /> 重跑</button>
          <button className="btn primary"><Icon name="send" size={11} /> 分享報告</button>
        </div>
      </div>

      {/* Progress bar */}
      <div style={{ padding: '12px 18px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: 'var(--text-3)', marginBottom: 6 }}>
          <span>整體進度</span>
          <span className="mono" style={{ color: 'var(--text)' }}>{Math.round(progress)}%</span>
          <span style={{ flex: 1 }}></span>
          <span><span className="pulse-dot" style={{ display: 'inline-block', verticalAlign: 'middle', marginRight: 4 }}></span>執行中 · 預計剩餘 8.4s</span>
        </div>
        <div style={{ height: 4, background: 'var(--bg-sunk)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: `${progress}%`, height: '100%', background: 'linear-gradient(90deg, var(--accent), oklch(60% 0.15 295))', transition: 'width 0.4s' }}></div>
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === 'graph' ? 'active' : ''}`} onClick={() => setTab('graph')}>Pipeline 圖</button>
        <button className={`tab ${tab === 'log' ? 'active' : ''}`} onClick={() => setTab('log')}>執行日誌</button>
        <button className={`tab ${tab === 'output' ? 'active' : ''}`} onClick={() => setTab('output')}>診斷結果</button>
      </div>

      <div className="tab-body">
        {tab === 'graph' && (
          <div className="pipeline-graph">
            {PIPELINE_STEPS.map((s, i) => (
              <div key={s.id} className={`pipe-step pipe-${s.status}`}>
                <div className="pipe-num">{i + 1}</div>
                <div className="pipe-card">
                  <div className="pipe-card-head">
                    <span className="pipe-card-name">{s.name}</span>
                    <span className="mono" style={{ fontSize: 10, color: 'var(--text-4)' }}>{s.duration}</span>
                  </div>
                  <div className="pipe-card-node">
                    <Icon name="server" size={10} /> <span className="mono">{s.node}</span>
                  </div>
                  {s.output && <div className="pipe-card-out">{s.output}{s.status === 'running' && <span className="cursor">▌</span>}</div>}
                </div>
                {i < PIPELINE_STEPS.length - 1 && <div className="pipe-conn"></div>}
              </div>
            ))}
          </div>
        )}

        {tab === 'log' && (
          <div className="pipe-log mono">
            <div><span style={{ color: 'var(--text-4)' }}>14:11:25.041</span> <span style={{ color: 'var(--accent)' }}>[INIT]</span> Pipeline #1940 starting · trigger=cluster:c1</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:25.123</span> <span style={{ color: 'var(--ok)' }}>[s1]</span> patrol-pipeline.fetch(eqp=EQP-03, n=200) → ok (2.3s)</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:27.501</span> <span style={{ color: 'var(--ok)' }}>[s2]</span> rule-engine.match(SPC_OOC_RULE_3_OF_5) → 3 violations</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:28.342</span> <span style={{ color: 'var(--ok)' }}>[s3]</span> apc-fetcher.pull(lot=LOT-0043) → 28 params</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:29.781</span> <span style={{ color: 'var(--ok)' }}>[s4]</span> baseline.compare(window=7d) → 2 outliers</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:32.901</span> <span style={{ color: 'var(--med)' }}>[s4]</span> WARN: etch_rate_pred σ=2.4 exceeds threshold</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:33.012</span> <span style={{ color: 'var(--ok)' }}>[s5]</span> graph.find_correlated(bay=A, group=chamber) → 1 hit (EQP-07)</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:37.233</span> <span style={{ color: 'var(--ok)' }}>[s5]</span> correlation_score=0.86 (high)</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:37.412</span> <span style={{ color: 'var(--accent)' }}>[s6]</span> llm-reasoner.invoke(model=claude-haiku-4-5)</div>
            <div><span style={{ color: 'var(--text-4)' }}>14:11:38.012</span> <span style={{ color: 'var(--text-3)' }}>[s6]</span> streaming... 412/1024 tokens<span className="cursor">▌</span></div>
          </div>
        )}

        {tab === 'output' && (
          <div style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.65 }}>
            <div className="synth" style={{ margin: '0 0 14px' }}>
              <div className="synth-icon"><Icon name="sparkles" size={14} /></div>
              <div className="synth-body">
                <div className="synth-tag">最終診斷（信心度 86%）</div>
                <strong>Root cause: chamber drift (BAY-A · chamber group #3)</strong><br/>
                EQP-03 與 EQP-07 共用同一 chamber 控制群組，etch_rate_pred 在過去 4 小時持續上升 2.4σ，gas_flow_comp 同步下降 1.8σ。此為 chamber 內部 conditioning 失效之典型 signature，與歷史 pattern #2403/#2425/#2451 高度相符。
              </div>
            </div>

            <div className="data-section-title"><Icon name="zap" size={12} /> 建議行動順序</div>
            <ol style={{ paddingLeft: 20, marginTop: 8 }}>
              <li>立即將 EQP-03 + EQP-07 切至 hold 狀態（影響 14 個進行中 lot，但避免後續 18 個 lot 也產生 OOC）</li>
              <li>派工給 KH（chamber 領域專家）+ 通知 BAY-A shift leader</li>
              <li>排入 chamber conditioning recipe 重新執行（預計 35 分鐘）</li>
              <li>conditioning 完成後跑 3 片 dummy wafer 驗證後再放正式 lot</li>
            </ol>

            <div className="data-section-title" style={{ marginTop: 16 }}><Icon name="info" size={12} /> 證據鏈</div>
            <ul style={{ paddingLeft: 20, marginTop: 8, fontSize: 12 }}>
              <li>SPC: STEP_007 xbar 連續 3 點偏移（14:09 / 14:11 / 14:16）</li>
              <li>APC: etch_rate_pred 從 baseline 23.5 → 32.4（+38%）</li>
              <li>歷史: 過去 90 天此 chamber group 共觸發 4 次同 pattern，3 次以 conditioning 解決</li>
              <li>關聯: EQP-07 同期間 OOC × 8（相關係數 0.86）</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};

window.PipelineRunPage = PipelineRunPage;
