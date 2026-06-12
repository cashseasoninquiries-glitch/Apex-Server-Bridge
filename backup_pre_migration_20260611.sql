--
-- PostgreSQL database dump
--

\restrict TcMBmCpRpQuFfEQmFd8JYwVNQ8Y34kEBYcCeFxWMGIubQftOuAnmg1NbGfypyAf

-- Dumped from database version 15.18
-- Dumped by pg_dump version 15.18

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: execution_ledger; Type: TABLE; Schema: public; Owner: apex_admin
--

CREATE TABLE public.execution_ledger (
    execution_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    strategy_id character varying(64) NOT NULL,
    symbol character varying(16) NOT NULL,
    direction character varying(10) NOT NULL,
    execution_price numeric(18,8) NOT NULL,
    quantity numeric(18,8) NOT NULL,
    run_id uuid NOT NULL,
    is_simulated boolean DEFAULT false,
    CONSTRAINT execution_ledger_direction_check CHECK (((direction)::text = ANY ((ARRAY['BUY'::character varying, 'SELL'::character varying, 'LIQUIDATE'::character varying])::text[])))
);


ALTER TABLE public.execution_ledger OWNER TO apex_admin;

--
-- Name: strategy_signals; Type: TABLE; Schema: public; Owner: apex_admin
--

CREATE TABLE public.strategy_signals (
    "timestamp" timestamp with time zone NOT NULL,
    strategy_id character varying(64) NOT NULL,
    symbol character varying(16) NOT NULL,
    signal_value smallint NOT NULL,
    stop_loss numeric(18,8),
    take_profit numeric(18,8),
    metadata jsonb,
    CONSTRAINT strategy_signals_signal_value_check CHECK ((signal_value = ANY (ARRAY['-1'::integer, 0, 1])))
);


ALTER TABLE public.strategy_signals OWNER TO apex_admin;

--
-- Data for Name: execution_ledger; Type: TABLE DATA; Schema: public; Owner: apex_admin
--

COPY public.execution_ledger (execution_id, "timestamp", strategy_id, symbol, direction, execution_price, quantity, run_id, is_simulated) FROM stdin;
4cecbd81-bd90-4e1d-bc93-e99f625288e0	2026-05-19 14:50:04.717203+00	ICT_REVERSAL_V1	AAPL	BUY	0.00000000	0.00000000	15ba4593-52ea-4dce-b2a4-870a281964dd	t
\.


--
-- Data for Name: strategy_signals; Type: TABLE DATA; Schema: public; Owner: apex_admin
--

COPY public.strategy_signals ("timestamp", strategy_id, symbol, signal_value, stop_loss, take_profit, metadata) FROM stdin;
2026-05-19 14:50:04.711045+00	ICT_REVERSAL_V1	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "strategy_id": "ICT_REVERSAL_V1"}
2026-05-21 00:43:44.973157+00	MOMENTUM_BREAKOUT_V2	NQ	1	\N	\N	{"price": 18500.25, "action": "LONG", "ticker": "NQ", "strategy_id": "MOMENTUM_BREAKOUT_V2"}
2026-05-21 02:33:00.562663+00	TEST_WEBHOOK_V1	TSLA	1	\N	\N	{"price": 175.5, "action": "LONG", "ticker": "TSLA", "passphrase": "apex_master_key_2026", "strategy_id": "TEST_WEBHOOK_V1"}
2026-05-22 14:18:32.350089+00	TV_LIVE_TEST	BTCUSD	1	\N	\N	{"price": 76826, "action": "LONG", "ticker": "BTCUSD", "passphrase": "apex_master_key_2026", "strategy_id": "TV_LIVE_TEST"}
2026-05-28 21:04:02.229884+00	test_001	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "passphrase": "test", "strategy_id": "test_001"}
2026-05-28 21:12:51.570112+00	test_001	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "passphrase": "test", "strategy_id": "test_001"}
2026-05-29 11:13:17.987179+00	test_001	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "passphrase": "test", "strategy_id": "test_001"}
2026-05-29 11:27:33.878939+00	test_001	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "passphrase": "test", "strategy_id": "test_001"}
2026-05-29 12:23:40.320447+00	test_001	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "passphrase": "test", "strategy_id": "test_001"}
2026-05-29 14:15:15.645833+00	test_001	AAPL	1	\N	\N	{"action": "LONG", "status": "executed", "ticker": "AAPL", "order_id": "871fce06-5b53-4253-bb4f-6868f91a745a", "passphrase": "test", "strategy_id": "test_001"}
2026-05-29 14:17:25.725127+00	test_001	AAPL	1	\N	\N	{"action": "LONG", "status": "executed", "ticker": "AAPL", "order_id": "7d04ea83-36ad-4ebc-97cf-1b6f134d4f58", "passphrase": "test", "strategy_id": "test_001"}
2026-06-01 14:30:10.201755+00	strategy_mvp_sma	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "timestamp": "2026-06-01T14:30:10.167732+00:00", "strategy_id": "strategy_mvp_sma"}
2026-06-02 14:30:00.277663+00	strategy_mvp_sma	AAPL	1	\N	\N	{"action": "LONG", "ticker": "AAPL", "timestamp": "2026-06-02T14:30:00.233585+00:00", "strategy_id": "strategy_mvp_sma"}
\.


--
-- Name: execution_ledger execution_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: apex_admin
--

ALTER TABLE ONLY public.execution_ledger
    ADD CONSTRAINT execution_ledger_pkey PRIMARY KEY (execution_id);


--
-- Name: strategy_signals strategy_signals_pkey; Type: CONSTRAINT; Schema: public; Owner: apex_admin
--

ALTER TABLE ONLY public.strategy_signals
    ADD CONSTRAINT strategy_signals_pkey PRIMARY KEY ("timestamp", strategy_id, symbol);


--
-- Name: idx_execution_time; Type: INDEX; Schema: public; Owner: apex_admin
--

CREATE INDEX idx_execution_time ON public.execution_ledger USING btree ("timestamp" DESC);


--
-- Name: idx_signals_time_strat; Type: INDEX; Schema: public; Owner: apex_admin
--

CREATE INDEX idx_signals_time_strat ON public.strategy_signals USING btree (strategy_id, "timestamp" DESC);


--
-- PostgreSQL database dump complete
--

\unrestrict TcMBmCpRpQuFfEQmFd8JYwVNQ8Y34kEBYcCeFxWMGIubQftOuAnmg1NbGfypyAf

