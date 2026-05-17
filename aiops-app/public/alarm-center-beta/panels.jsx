// Detail panel and AI Agent panel

const DetailPanel = ({ cluster, onOpenPipeline, view, onBack }) => {
  const { PROCESS_HISTORY, APC_PARAMS, fmtAgo } = window.MOCK;
  const [tab, setTab] = React.useState('cause');

  if (!cluster) return null;
  if (view === 'pipeline') return <PipelineRunPage onBack={onBack} />;

  return (
    <div className="detail">
      <div className="detail-head">
        <div className={`sev-icon ${cluster.severity}`}>
          <Icon name="alert" size={16} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="detail-title">AI 診斷報告 · {cluster.tool}</div>
          <div className="detail-sub">
            {cluster.title} · 群集了 <strong style={{ color: 'var(--text-2)' }}>{cluster.count}</strong> 個原始告警 · 最後發生 {fmtAgo(cluster.lastAt)} ago
          </div>
        </div>
        <div className="detail-actions">
          <button className="btn"><Icon name="bookmark" size={12} /> 加入觀察</button>
          <button className="btn"><Icon name="merge" size={12} /> 合併</button>
          <button className="btn primary"><Icon name="users" size={12} /> 派工</button>
        </div>
      </div>

      <div className="synth">
        <div className="synth-icon"><Icon name="sparkles" size={14} /></div>
        <div className="synth-body">
          <div className="synth-tag">AI 綜合診斷</div>
          根據 <strong>{cluster.tool}</strong> 最近 5 次製程中出現 <strong>3 次 OOC</strong> 的高嚴重度告警，研判為<strong>真異常</strong>。
          {' '}與 <strong>EQP-07</strong> 同 chamber 群組亦有相似 etch rate 偏移趨勢，<strong>建議合併處理</strong>。
          建議立即停機檢查 chamber 製程參數設定，並執行設備校正程序以確保製程穩定性。
          <span style={{ color: 'var(--text-3)', fontSize: 11, marginLeft: 4 }}>(信心度 {Math.round((cluster.rootcause_confidence || 0.86) * 100)}%)</span>
        </div>
      </div>

      <div className="actions-card">
        <div className="actions-head">
          <div className="actions-head-left">
            <span className="actions-head-tag">下一步</span>
            <span>建議行動 · 點擊執行</span>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-3)' }}>剩餘 4 步</span>
        </div>
        <div className="action-row recommended">
          <div className="action-num">1</div>
          <div>
            <div className="action-text">通知 EQP-03 owner — <strong>KH</strong> 並標記為「優先處理」</div>
            <div className="action-text-sub">同時連動 EQP-07 cluster 一併指派</div>
          </div>
          <button className="btn primary"><Icon name="send" size={11} /> 派工</button>
        </div>
        <div className="action-row">
          <div className="action-num">2</div>
          <div>
            <div className="action-text">將 EQP-03 切換至 hold 狀態，停止接料</div>
            <div className="action-text-sub">影響 8 個進行中 lot · 預計影響 throughput 12%</div>
          </div>
          <button className="btn"><Icon name="pause" size={11} /> 切換 Hold</button>
        </div>
        <div className="action-row">
          <div className="action-num">3</div>
          <div>
            <div className="action-text">合併 EQP-03 + EQP-07 為單一 incident</div>
            <div className="action-text-sub">兩個 cluster 共 26 個原始告警 → 1 個事件</div>
          </div>
          <button className="btn"><Icon name="merge" size={11} /> 合併</button>
        </div>
        <div className="action-row">
          <div className="action-num">4</div>
          <div>
            <div className="action-text">啟動深度診斷 pipeline (#1940)</div>
            <div className="action-text-sub">執行 APC 參數比對 + chamber drift 檢測</div>
          </div>
          <button className="btn"><Icon name="play" size={11} /> 執行</button>
        </div>
      </div>

      <div style={{ padding: '0 18px', display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
        <button className="btn" onClick={onOpenPipeline}>
          <Icon name="cpu" size={11} /> 進入深度診斷 Pipeline #1940
        </button>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === 'cause' ? 'active' : ''}`} onClick={() => setTab('cause')}>
          觸發原因
        </button>
        <button className={`tab ${tab === 'deep' ? 'active' : ''}`} onClick={() => setTab('deep')}>
          深度診斷 <span className="tab-count">1</span>
        </button>
        <button className={`tab ${tab === 'related' ? 'active' : ''}`} onClick={() => setTab('related')}>
          相關告警 <span className="tab-count">{cluster.count}</span>
        </button>
        <button className={`tab ${tab === 'history' ? 'active' : ''}`} onClick={() => setTab('history')}>
          歷史
        </button>
      </div>

      <div className="tab-body">
        {tab === 'cause' && (
          <>
            <div className="trigger-card">
              <Icon name="alert" size={16} className="trigger-icon" />
              <div>
                <div className="trigger-title">條件達成 — 已觸發警報</div>
                <div className="trigger-sub">SPC rule: 5 連續 process 中 ≥ 3 次 OOC · 偵測到機台異常，請立即檢查</div>
              </div>
            </div>

            <div className="data-section">
              <div className="data-section-title">
                <Icon name="chart" size={12} /> 最近 5 次 Process 資料
              </div>
              <div className="data-section-sub">PATROL PIPELINE 回傳 · 顯示機台最近 5 次 Process 的詳細資料</div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>eventTime</th>
                    <th>toolID</th>
                    <th>lotID</th>
                    <th>step</th>
                    <th>spc_status</th>
                    <th style={{ textAlign: 'right' }}>xbar value</th>
                    <th style={{ textAlign: 'right' }}>UCL</th>
                  </tr>
                </thead>
                <tbody>
                  {PROCESS_HISTORY.map((r, i) => (
                    <tr key={i} className={r.bad ? 'cell-row-bad' : ''}>
                      <td>{r.time}</td>
                      <td>{r.lot.split('-')[0] === 'EQP' ? r.lot : 'EQP-03'}</td>
                      <td>{r.lot}</td>
                      <td>{r.step}</td>
                      <td className={r.bad ? 'cell-bad' : 'cell-good'}>{r.spc}</td>
                      <td style={{ textAlign: 'right' }}>{r.value.toFixed(3)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-3)' }}>{r.ucl.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {tab === 'deep' && (
          <>
            <div className="data-section">
              <div className="data-section-title">
                <Icon name="cpu" size={12} /> AUTO-CHECK 診斷 — APC 參數明細 (PIPELINE RUN #1940)
              </div>
              <div className="data-section-sub">最近一次 OOC 事件 LOT-0043 · 比對 baseline 後標示偏移欄位</div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>param_name</th>
                    <th style={{ textAlign: 'right' }}>value</th>
                    <th style={{ textAlign: 'right' }}>baseline</th>
                    <th style={{ textAlign: 'right' }}>Δ σ</th>
                    <th>status</th>
                  </tr>
                </thead>
                <tbody>
                  {APC_PARAMS.map((p, i) => (
                    <tr key={i} className={p.bad ? 'cell-row-bad' : ''}>
                      <td>{p.name}</td>
                      <td style={{ textAlign: 'right' }}>{p.value.toFixed(3)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text-3)' }}>{(p.value * (p.bad ? 0.7 : 0.95)).toFixed(3)}</td>
                      <td style={{ textAlign: 'right' }} className={p.bad ? 'cell-bad' : ''}>{p.bad ? '+2.4σ' : '0.3σ'}</td>
                      <td className={p.bad ? 'cell-bad' : 'cell-good'}>{p.bad ? 'DRIFT' : 'OK'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {tab === 'related' && (
          <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
            <p style={{ marginTop: 0 }}>本 cluster 包含 {cluster.count} 個原始告警，已自動依時間/條件去重。</p>
            <table className="data-table" style={{ marginTop: 8 }}>
              <thead>
                <tr>
                  <th>time</th>
                  <th>tool</th>
                  <th>lot</th>
                  <th>rule</th>
                  <th>status</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: Math.min(cluster.count, 8) }).map((_, i) => (
                  <tr key={i}>
                    <td>{window.MOCK.fmtFull(window.MOCK.minsAgo(6 + i * 5))}</td>
                    <td>{cluster.tool}</td>
                    <td>LOT-{(43 - i * 7).toString().padStart(4, '0')}</td>
                    <td>SPC_OOC_RULE_3_OF_5</td>
                    <td className="cell-bad">OPEN</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'history' && (
          <div style={{ fontSize: 12, color: 'var(--text-2)' }}>
            <p style={{ marginTop: 0 }}>過去 30 天 {cluster.tool} 同類事件：</p>
            <ul style={{ paddingLeft: 16 }}>
              <li>04-25 14:02 · STEP_007 OOC × 4 · 已解決 (chamber clean)</li>
              <li>04-21 09:45 · STEP_007 OOC × 2 · 已解決 (recipe rollback)</li>
              <li>04-12 21:33 · etch rate drift · 已解決 (PM)</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};

const AgentPanel = ({ cluster, onClose, position, onOpenPipeline }) => {
  const { PLAN_STEPS } = window.MOCK;
  const [scenario, setScenario] = React.useState('focus');

  return (
    <div className="agent">
      <div className="agent-head">
        <div className="agent-title-row">
          <div className="agent-avatar"><Icon name="sparkles" size={13} /></div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="agent-title">AI Agent · 副駕模式</div>
            <div className="agent-sub">tokens 5,705 · cache 1,150 · turn 8/40</div>
          </div>
          {position === 'floating' && (
            <button className="btn icon" onClick={onClose}><Icon name="x" size={12} /></button>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
          {[
            { id: 'focus', label: '焦點' },
            { id: 'scripts', label: '自動腳本' },
            { id: 'console', label: 'Console' },
          ].map(t => (
            <button key={t.id} onClick={() => setScenario(t.id)}
              className={`list-mode-btn ${scenario === t.id ? 'active' : ''}`}
              style={{ flex: 1, fontSize: 11, padding: '4px 8px', borderRadius: 5, border: 'none', background: scenario === t.id ? 'var(--bg-soft)' : 'transparent', color: scenario === t.id ? 'var(--text)' : 'var(--text-3)', fontWeight: 500 }}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="agent-body">
        {scenario === 'focus' && <>
        <div className="agent-block">
          <div className="agent-block-head">
            <span>當前焦點</span>
            <span className="agent-block-tag ai">FOCUS</span>
          </div>
          <div className="agent-block-body">
            正在分析 <strong>{cluster?.tool || 'EQP-03'}</strong> 與 <strong>EQP-07</strong> 的關聯性。
            兩台機台位於 BAY-A 同 chamber 群組，且都在 STEP_007 出現 OOC，<strong>有 86% 機率是同一根因</strong>。
          </div>
          <div className="suggest-btns">
            <button className="suggest-btn primary"><Icon name="merge" size={11} /> 合併兩個 cluster</button>
            <button className="suggest-btn"><Icon name="eye" size={11} /> 顯示 chamber drift 圖</button>
            <button className="suggest-btn"><Icon name="info" size={11} /> 查看相似歷史</button>
          </div>
        </div>

        <div className="agent-block">
          <div className="agent-block-head">
            <span>診斷計畫</span>
            <span className="agent-block-tag">5 / 5 steps</span>
          </div>
          {PLAN_STEPS.map((s) => (
            <div key={s.id} className={`plan-step ${s.status}`}>
              <div className="plan-step-icon">
                {s.status === 'done' && <Icon name="check" size={9} />}
                {s.status === 'active' && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }}></span>}
              </div>
              <div>{s.text}</div>
            </div>
          ))}
        </div>

        <div className="agent-block">
          <div className="agent-block-head">
            <span>快速命令</span>
            <span className="agent-block-tag">COMMAND</span>
          </div>
          <div className="suggest-btns">
            <button className="suggest-btn">最近一次 OOC SPC chart 趨勢</button>
            <button className="suggest-btn">列出影響 lots</button>
            <button className="suggest-btn">同 chamber 群組所有 tool</button>
            <button className="suggest-btn">建立 incident</button>
            <button className="suggest-btn">通知 shift leader</button>
          </div>
        </div>
        </>}

        {scenario === 'scripts' && <>
        <div className="agent-block">
          <div className="agent-block-head">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="zap" size={11} /> Chamber Drift Recovery
            </span>
            <span className="agent-block-tag ai">PATTERN #2403</span>
          </div>
          <div className="agent-block-body" style={{ fontSize: 11.5 }}>
            <div style={{ paddingLeft: 12, borderLeft: '2px solid var(--accent)', margin: '4px 0' }}>
              <div>1. 通知 owner KH + shift leader</div>
              <div>2. 將 EQP-03/07 切 hold（影響 14 lots）</div>
              <div>3. 開立 PM 單 #PM-2026-0430-A03</div>
              <div>4. 執行 chamber conditioning recipe</div>
            </div>
          </div>
          <div className="suggest-btns">
            <button className="suggest-btn primary"><Icon name="play" size={11} /> 執行全套</button>
            <button className="suggest-btn">逐步確認</button>
          </div>
        </div>

        <div className="agent-block">
          <div className="agent-block-head">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="zap" size={11} /> False-Alarm Suppress
            </span>
            <span className="agent-block-tag">PATTERN #1102</span>
          </div>
          <div className="agent-block-body" style={{ fontSize: 11.5 }}>
            標記為 false alarm 並建立 1 小時抑制規則，避免重複觸發。
          </div>
          <div className="suggest-btns">
            <button className="suggest-btn">標記 + 抑制</button>
            <button className="suggest-btn">先查資料</button>
          </div>
        </div>

        <div className="agent-block">
          <div className="agent-block-head">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="zap" size={11} /> Recipe Rollback
            </span>
            <span className="agent-block-tag">PATTERN #1888</span>
          </div>
          <div className="agent-block-body" style={{ fontSize: 11.5 }}>
            recipe 版本回滾到上一穩定版（minor rev -1），影響 EQP-15。
          </div>
          <div className="suggest-btns">
            <button className="suggest-btn">執行 rollback</button>
          </div>
        </div>

        <div className="agent-block">
          <div className="agent-block-head">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="zap" size={11} /> Sensor Calibration
            </span>
            <span className="agent-block-tag">PATTERN #2201</span>
          </div>
          <div className="agent-block-body" style={{ fontSize: 11.5 }}>
            EQP-21 temperature sensor 校正流程，預計 12 分鐘。
          </div>
          <div className="suggest-btns">
            <button className="suggest-btn">啟動校正</button>
          </div>
        </div>
        </>}

        {scenario === 'console' && <>
        <div className="agent-block" style={{ background: 'var(--bg-sunk)', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-2)', lineHeight: 1.7 }}>
          <div><span style={{ color: 'var(--accent)' }}>{'>'}</span> 你: 為什麼 EQP-03 的 etch_rate 偏移？</div>
          <div style={{ color: 'var(--text)', marginTop: 6 }}>
            根據 APC 資料，etch_rate_pred 從 baseline 23.5 → 32.4（+38%），
            同時 gas_flow_comp 從 -1.0 → -1.8。這個組合在歷史上曾出現過 4 次，
            其中 3 次都是 chamber conditioning 失效造成。
            <button onClick={onOpenPipeline} style={{ display: 'block', marginTop: 8, color: 'var(--accent)', background: 'transparent', border: 'none', padding: 0, fontFamily: 'inherit', fontSize: 11 }}>
              → 查看完整 pipeline #1940
            </button>
          </div>
          <div style={{ marginTop: 10, color: 'var(--text-3)' }}>
            <span style={{ color: 'var(--accent)' }}>{'>'}</span> 你: 還影響哪些 lot？
          </div>
          <div style={{ color: 'var(--text)', marginTop: 6 }}>
            進行中受影響：14 個 lot · 已完成但需 reflow：3 個 · 等待中：2 個。
            最緊急：LOT-0043（客戶 ABC，今晚 22:00 出貨）<span className="cursor">▌</span>
          </div>
        </div>
        </>}

        <div className="agent-block" style={{ borderColor: 'oklch(85% 0.04 265)', background: 'var(--accent-bg)' }}>
          <div className="agent-block-head">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="zap" size={11} /> 自動腳本就緒
            </span>
            <span className="agent-block-tag ai">AUTO-RUN</span>
          </div>
          <div className="agent-block-body">
            偵測到此情境屬於已知 pattern (#2403/#2425/#2451)，可一鍵執行：通知 owner → hold 機台 → 開立 PM 單。
          </div>
          <div className="suggest-btns">
            <button className="suggest-btn primary">執行全套 (3 步)</button>
            <button className="suggest-btn">逐步確認</button>
          </div>
        </div>
      </div>

      <div className="agent-foot">
        <div className="agent-input">
          <Icon name="sparkles" size={12} />
          <input placeholder="輸入訊息或 / 啟動指令…" />
          <span className="kbd">⌘K</span>
          <button className="agent-send"><Icon name="send" size={12} stroke={2} /></button>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { DetailPanel, AgentPanel });
