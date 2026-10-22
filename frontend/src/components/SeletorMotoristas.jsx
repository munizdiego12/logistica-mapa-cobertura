// Escolha dos motoristas da roteirização (campo de pesquisa com seleção múltipla). Só os ATIVOS aparecem; a busca olha nome e
// código; com loja escolhida, "Desta loja" vem primeiro e "Outros motoristas" depois (a busca alcança todos). A lista renderiza
// no máximo LIMITE_DA_LISTA itens, então funciona com centenas de motoristas.
// "Marcar todos" vale só para os motoristas da loja escolhida; "Limpar" desmarca tudo.
import { useMemo, useState } from 'react';
import ComboboxMultiplo from './ComboboxMultiplo';
import { agruparParaRoteirizacao, avisoDeLimite, motoristasDaLoja } from '../services/motoristas';
import { rotuloDoMotorista, alternarMarcacao, marcarVarios, motoristasMarcados, etiquetaDoMotorista } from '../services/selecaoMotoristas';
import { OPCOES_DE_VIAGENS, AVISO_VIAGENS, textoRecomendado } from '../services/roteirizacao';

export default function SeletorMotoristas({ motoristas, lojaId, rotasHoje, pedidosHoje = {}, selecionados, onMudar, viagens = {}, onViagens, recomendado = 1 }) {
  const [busca, setBusca] = useState('');

  const resultado = useMemo(() => agruparParaRoteirizacao(motoristas, lojaId, busca), [motoristas, lojaId, busca]);
  const grupos = useMemo(
    () => resultado.grupos.map((g) => ({
      chave: g.chave,
      titulo: g.titulo,
      itens: g.itens.map((m) => ({ id: m.id, rotulo: rotuloDoMotorista(m, rotasHoje[String(m.id)] || 0, pedidosHoje[String(m.id)] || 0), detalhe: m.codigo || '' })),
    })),
    [resultado, rotasHoje, pedidosHoje],
  );
  const chips = useMemo(
    () => motoristasMarcados(motoristas, selecionados).map((m) => ({ id: m.id, rotulo: etiquetaDoMotorista(m) })),
    [motoristas, selecionados],
  );
  const daLoja = useMemo(() => motoristasDaLoja(motoristas, lojaId), [motoristas, lojaId]);
  const marcados = useMemo(() => motoristasMarcados(motoristas, selecionados), [motoristas, selecionados]);

  const botao = 'px-2 py-0.5 rounded border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-slate-300';

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <button
          type="button"
          onClick={() => onMudar(marcarVarios(selecionados, daLoja.map((m) => m.id)))}
          disabled={daLoja.length === 0}
          title={lojaId === null ? 'Escolha a loja de origem para marcar os motoristas dela' : undefined}
          className={botao}
        >
          Marcar todos desta loja{lojaId !== null ? ` (${daLoja.length})` : ''}
        </button>
        <button type="button" onClick={() => onMudar([])} disabled={selecionados.length === 0} className={botao}>
          Limpar
        </button>
      </div>

      <ComboboxMultiplo
        rotulo="Motoristas da roteirização"
        placeholder="Pesquise o motorista (nome ou código)"
        grupos={grupos}
        selecionados={selecionados}
        chips={chips}
        busca={busca}
        onBusca={setBusca}
        onAlternar={(id) => onMudar(alternarMarcacao(selecionados, id))}
        onRemover={(id) => onMudar(selecionados.filter((x) => x !== id))}
        aviso={avisoDeLimite(resultado)}
        textoVazio="Nenhum motorista encontrado"
      />

      {onViagens && marcados.length > 0 && (
        <div className="space-y-1.5 p-2 rounded-lg bg-slate-950/50 border border-slate-800" aria-label="Quantas rotas cada motorista vai fazer">
          {marcados.map((m) => (
            <label key={m.id} className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-[11px] text-slate-300">
              <span className="font-semibold text-slate-100 truncate max-w-[45%]">{m.nome}</span>
              <span className="flex items-center gap-1.5">
                <span className="text-slate-400">Quantas rotas o motorista vai fazer?</span>
                <select
                  value={viagens[m.id] ?? ''}
                  onChange={(e) => onViagens(m.id, e.target.value)}
                  aria-label={`Quantas rotas ${m.nome} vai fazer`}
                  className="px-1.5 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-[11px]"
                >
                  {OPCOES_DE_VIAGENS.map((o) => <option key={o.valor} value={o.valor}>{o.rotulo}</option>)}
                </select>
              </span>
              <span className="w-full text-[10px] text-slate-500">{textoRecomendado(recomendado)}</span>
            </label>
          ))}
          <p className="text-[10px] text-amber-300/80">{AVISO_VIAGENS}</p>
        </div>
      )}
    </div>
  );
}
