"""Read-only local feasibility check. This entry point never creates orders."""
import argparse
import json
import os
import time
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from itertools import permutations

from jin_trading.arbitrage import number
from jin_trading.brokers import SpotBroker
from jin_trading.execution import order_size
from jin_trading.feeds import PublicFeed
from jin_trading.supervisor import Portfolio
from jin_trading.universe import plan_batches, route_groups


def _routes(pairs):
    """Enumerate both directions, including routes whose books are unavailable."""
    for group in route_groups(pairs):
        if len(group) != 3:
            continue
        for route in permutations(group):
            asset, visited = 'USDT', {'USDT'}
            for index, pair in enumerate(route):
                assets = pair.split('-')
                if asset not in assets:
                    break
                asset = next(a for a in assets if a != asset)
                if index < 2 and asset in visited:
                    break
                visited.add(asset)
            else:
                if asset == 'USDT' and len(visited) == 3:
                    yield route


def _account_fee(broker, pair):
    """Use only finite percentage taker fees; failures retain an explicit estimate."""
    checked_at = time.time()
    cached = broker.verified_fees.get(pair)
    if cached and 0 <= checked_at - cached[0] <= 120:
        return {'taker': str(cached[1]), 'source': 'account', 'verified': True,
                'checked_at': cached[0]}
    try:
        capabilities = getattr(broker.client, 'has', {})
        if isinstance(capabilities, dict) and capabilities.get('fetchTradingFee') in (False, 'emulated'):
            raise ValueError('Account-specific fee lookup unavailable')
        raw = broker.client.fetch_trading_fee(pair.replace('-', '/'))
        fee = number(raw['taker'])
        if not 0 <= fee < 1 or raw.get('percentage') is False:
            raise ValueError('Unsupported account fee')
        broker.verified_fees[pair] = (checked_at, fee)
        return {'taker': str(fee), 'source': 'account', 'verified': True,
                'checked_at': checked_at}
    except Exception as exc:
        # Exception text from authenticated requests may contain sensitive data.
        broker.verified_fees.pop(pair, None)
        return {'source': 'public_assumption', 'verified': False,
                'checked_at': checked_at, 'error': type(exc).__name__}


def _limit_reason(book, asset, amount, slippage):
    """Explain a rejected canonical order without relaxing its acceptance rules."""
    relaxed = replace(book, min_size=Decimal('0'), min_notional=Decimal('0'),
                      max_size=Decimal('1e100'))
    try:
        side, quantity, price, _ = order_size(relaxed, asset, amount, slippage)
    except ValueError as exc:
        return 'insufficient_depth' if 'depth' in str(exc).lower() else 'quantity_below_step'
    if quantity < book.min_size:
        return 'below_min_size'
    if quantity > book.max_size:
        return 'above_max_size'
    remaining, notional = quantity, Decimal('0')
    for level, size in (book.asks if side == 'buy' else book.bids):
        used = min(remaining, size)
        notional += used * level
        remaining -= used
        if not remaining:
            break
    if min(notional, quantity * price) < book.min_notional:
        return 'below_min_notional'
    return 'market_limits'


def _route_report(client, pairs, books, fees, amount, now):
    slippage, threshold = Decimal('.001'), Decimal('.0035')
    result = {'route': tuple((client.id, pair) for pair in pairs), 'input': str(amount),
              'technically_feasible': False, 'profitable': False, 'legs': [],
              'checked_at': now,
              'personal_fees_verified': all(fees[pair]['verified'] for pair in pairs)}
    asset, current = 'USDT', amount
    for pair in pairs:
        leg = {'pair': pair, 'source': asset, 'input': str(current),
               'fee_source': fees[pair]['source'], 'status': 'rejected'}
        result['legs'].append(leg)
        book = books.get(pair)
        if book is not None:
            leg.update(book_timestamp=book.timestamp, book_age_seconds=now - book.timestamp)
        if book is None:
            leg['reason'] = 'book_unavailable'
        elif not 0 <= now - book.timestamp <= 3:
            leg['reason'] = 'stale_order_book'
        else:
            leg.update(taker_fee=str(book.fee), min_size=str(book.min_size),
                       min_notional=str(book.min_notional), max_size=str(book.max_size),
                       quantity_step=str(book.step))
            try:
                side, quantity, price, target = order_size(book, asset, current, slippage)
            except ValueError as exc:
                leg['reason'] = ('insufficient_depth' if 'depth' in str(exc).lower()
                                 else _limit_reason(book, asset, current, slippage))
            else:
                leg.update(side=side, quantity=str(quantity), limit_price=str(price),
                           order_notional=str(quantity * price), target=target)
                try:
                    symbol = pair.replace('-', '/')
                    precise_amount = number(client.amount_to_precision(symbol, float(quantity)))
                    precise_price = number(client.price_to_precision(symbol, float(price)))
                    if precise_amount != quantity:
                        leg['reason'] = 'quantity_precision_changed'
                    elif precise_price <= 0 or (side == 'buy' and precise_price > price) or (
                            side == 'sell' and precise_price < price):
                        leg['reason'] = 'price_precision_widens_limit'
                    elif quantity * precise_price < book.min_notional:
                        leg['reason'] = 'below_min_notional_after_precision'
                    elif sum((size for level, size in (book.asks if side == 'buy' else book.bids)
                              if (level <= precise_price if side == 'buy' else level >= precise_price)),
                             Decimal('0')) < quantity:
                        leg['reason'] = 'insufficient_depth_after_precision'
                    else:
                        asset, current = book.convert(asset, current / (1 + book.fee), slippage)
                        leg.update(status='passed', output=str(current),
                                   limit_price=str(precise_price),
                                   order_notional=str(quantity * precise_price))
                except Exception as exc:
                    leg.update(reason='precision_unavailable', error=type(exc).__name__)
        if leg['status'] != 'passed':
            result.update(reason=leg['reason'], rejected_leg=len(result['legs']))
            result['legs'].extend({'pair': later, 'status': 'not_checked',
                                   'reason': 'previous_leg_rejected'} for later in pairs[len(result['legs']):])
            return result
    result.update(technically_feasible=True, estimated_output=str(current),
                  estimated_profit=str(current - amount), net_fraction=str(current / amount - 1),
                  profitable=current > amount * (1 + threshold))
    result['reason'] = 'profit_threshold_met' if result['profitable'] else 'below_profit_threshold'
    return result


def check(client,feed,amount='5',db_path='data/jin-live.sqlite'):
    requested = number(amount)
    if requested <= 0:
        raise ValueError('Requested capital must be positive')
    portfolio=Portfolio(db_path,'live');portfolio.register([client.id])
    broker=SpotBroker(client,feed,armed=False)
    account=broker.sync(portfolio,client.id)
    amount=min(requested,number(account['free'].get('USDT',0)))
    result = {'mode': 'read-only', 'account': account, 'requested_capital': str(requested),
              'available_capital': str(max(amount, Decimal('0'))),
              'trade_budget': str(max(amount, Decimal('0')) * Decimal('.5')),
              'max_deploy_fraction': '0.5', 'min_profit': '0.0035', 'slippage': '0.001',
              'feasible': [], 'tradable_routes': [], 'rejected_routes': [], 'rejected_counts': {},
              'errors': [], 'fees': {}, 'fee_assumption': str(feed.fee),
              'started_at': time.time(),
              'personal_fees_verified': False, 'checked_pairs': 0, 'checked_routes': 0,
              'live_ready': False,
              'limitation': 'Read-only estimates; no orders submitted and no live execution approved'}
    if amount<=0:
        result['reason'] = 'No free USDT in spot account'
        result['completed_at'] = time.time()
        return result
    catalogue = tuple(sorted(set(feed.pairs())))
    batches=plan_batches({client.id:catalogue},12)
    reports={};checked_pairs=set()
    for pairs in batches:
        # Fetch account fees before books so authenticated latency does not age them.
        fees = {pair: _account_fee(broker, pair) for pair in pairs}
        books={};public_fees={}
        for pair in pairs:
            checked_pairs.add(pair)
            try:
                book = feed.book(pair)
                if book.exchange != client.id or book.pair != pair:
                    raise ValueError('Mismatched public book')
                public_fees[pair] = book.fee
                if fees[pair]['verified']:
                    book = replace(book, fee=number(fees[pair]['taker']))
                else:
                    fees[pair]['taker'] = str(book.fee)
                books[pair] = book
            except Exception as exc:
                result['errors'].append(pair+': '+type(exc).__name__)
        now = time.time()
        # Earlier fee reads in a slow batch cannot remain verified indefinitely.
        for pair, fee in fees.items():
            if fee['verified'] and not 0 <= now - fee['checked_at'] <= 120:
                fee.update(source='public_assumption', verified=False, error='StaleAccountFee')
                if pair in books:
                    original = public_fees[pair]
                    books[pair] = replace(books[pair], fee=number(original))
                    fee['taker'] = str(original)
        result['fees'].update(fees)
        for route in _routes(pairs):
            reports[route] = _route_report(client, route, books, fees, amount * Decimal('.5'), now)
    result['checked_pairs'] = len(checked_pairs)
    result['checked_routes'] = len(reports)
    result['tradable_routes'] = sorted((r for r in reports.values() if r['technically_feasible']),
                                      key=lambda r: number(r['net_fraction']), reverse=True)
    result['feasible'] = [r for r in result['tradable_routes'] if r['profitable']]
    result['rejected_routes'] = [r for r in reports.values() if not r['technically_feasible']]
    result['rejected_counts'] = dict(Counter(r['reason'] for r in result['rejected_routes']))
    result['personal_fees_verified'] = bool(result['fees']) and all(
        fee['verified'] for fee in result['fees'].values())
    result['reason'] = ('Profitable estimates found; execution and account acceptance remain unverified'
                        if result['feasible'] else 'Technically feasible routes are below the profit threshold'
                        if result['tradable_routes'] else 'No technically feasible route found')
    result['completed_at'] = time.time()
    return result


def main():
    parser=argparse.ArgumentParser(description='Read spot balance, permissions and 5 USDT feasibility; NO orders')
    parser.add_argument('--exchange',choices=['kucoin','binance','bitget'],default='kucoin')
    parser.add_argument('--db',default='data/jin-live.sqlite');parser.add_argument('--amount',default='5')
    args=parser.parse_args()
    try:import ccxt
    except ImportError:parser.error('Install the optional jin_trading/requirements-live.txt first')
    prefix='JIN_'+args.exchange.upper()+'_'
    options={'apiKey':os.environ.get(prefix+'KEY'),'secret':os.environ.get(prefix+'SECRET'),
             'password':os.environ.get(prefix+'PASSPHRASE'),'enableRateLimit':True,'timeout':8000,
             'options':{'defaultType':'spot'}}
    if not options['apiKey'] or not options['secret']:parser.error('Set exchange credentials locally in environment variables')
    client=getattr(ccxt,args.exchange)(options);client.load_markets()
    print(json.dumps(check(client,PublicFeed(args.exchange,'.002'),args.amount,args.db),default=str,indent=2))


if __name__=='__main__':main()

