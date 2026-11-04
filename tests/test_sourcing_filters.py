"""Incoming filtering preserves history and isolates account scope."""
import unittest
from tests import test_native_sourcing as fixtures
from mailcheck import db, sourcing_filters as filters, sourcing_csv


class IncomingFilterTests(unittest.TestCase):
    setUp=fixtures.NativeSheetTests.setUp
    tab=fixtures.NativeSheetTests.tab
    snapshot=fixtures.NativeSheetTests.snapshot
    # Reuse the isolated SQLite/web fixture, without inheriting its test methods.
    def jobs(self,tab=None):
        snap=self.native.snapshot(self.conn,tab or self.tab())
        return [r for r in snap['rows'][1:] if any(str(c['value']).strip() for c in r)]

    def add(self,rows,op='add',tab=None):
        tab=tab or self.tab()
        return self.native.append(self.conn,tab,op,self.native.snapshot(self.conn,tab)['revision'],rows)

    def test_duplicate_account_history_and_incoming_batch_are_compacted(self):
        self.add([['Acme','Engineer','https://jobs.test/1?utm_source=old']], 'old')
        book=self.native.create_book(self.conn,2)
        tab_id=self.native.create_tab(self.conn,book,self.account_id,'Other bidder')
        tab=self.native.owned(self.conn,tab_id,self.principal)
        result=self.add([['Acme','Engineer','https://jobs.test/1?jr_id=new'],
                         ['Beta','Engineer','https://jobs.test/2'],
                         ['Beta','Engineer','https://jobs.test/2/'],
                         ['Gamma','Engineer','https://jobs.test/3']],tab=tab)
        self.assertEqual(result['filtered']['duplicates'],2)
        self.assertEqual(len(self.jobs(tab)),2)
        self.assertEqual([r[0]['value'] for r in self.jobs(tab)],['Beta','Gamma'])
        self.assertEqual(len(self.jobs()),1)
        positions=[r[0] for r in self.conn.execute('SELECT position FROM native_rows WHERE tab_id=? ORDER BY position',(tab_id,))]
        self.assertEqual(positions,list(range(len(positions))))

    def test_same_job_is_allowed_for_another_account_and_distinct_job_ids(self):
        self.add([['Acme','Engineer','https://jobs.test/app?token=1']],'old')
        account=db.add_account(self.conn,label='other-filter',email='other@example.test')
        self.conn.commit()
        tab_id=self.native.create_tab(self.conn,self.book,account,'Other')
        tab=self.native.owned(self.conn,tab_id,self.principal)
        result=self.add([['Acme','Engineer','https://jobs.test/app?token=1'],['Acme','Engineer','https://jobs.test/app?token=2']],tab=tab)
        self.assertEqual(result['filtered']['duplicates'],0)
        self.assertEqual(len(self.jobs(tab)),2)

    def test_blocklist_only_affects_new_rows_and_retry_is_idempotent(self):
        self.add([['Blocked Co','Engineer','https://jobs.test/old']],'old')
        filters.set_companies(self.conn,['Blocked Co','BLOCKED CO'])
        self.conn.commit()
        revision=self.snapshot()['revision']
        rows=[['blocked-co.','Engineer','https://jobs.test/new'],['Allowed','Engineer','https://jobs.test/ok']]
        result=self.native.append(self.conn,self.tab(),'filtered',revision,rows)
        replay=self.native.append(self.conn,self.tab(),'filtered',revision,rows)
        self.assertEqual(result['filtered'],{'duplicates':0,'blocked_companies':1,'blocked_roles':0})
        self.assertEqual(replay['filtered'],result['filtered'])
        self.assertEqual([r[0]['value'] for r in self.jobs()],['Blocked Co','Allowed'])

    def test_csv_and_grid_save_apply_filters(self):
        filters.set_companies(self.conn,['Blocked'])
        self.conn.commit()
        result=sourcing_csv.import_rows(self.conn,self.tab(),'csv',self.snapshot()['revision'],text='Company,Role,Job link\nBlocked,Engineer,https://jobs.test/no\nAllowed,Engineer,https://jobs.test/yes')
        self.assertEqual(result['filtered']['blocked_companies'],1)
        base=self.snapshot()
        self.native.structure(self.conn,self.tab(),'insert',base['revision'],{'action':'insert_rows','count':1})
        base=self.snapshot()
        row=base['row_ids'][-1]
        changes=[{'row_id':row,'column_id':base['columns'][i]['id'],'expected_version':0,'value':value} for i,value in enumerate(['Allowed','Engineer','https://jobs.test/yes?jr_id=copy'])]
        result=self.native.save(self.conn,self.tab(),'paste',changes,compact_rows=True)
        self.assertEqual(result['filtered']['duplicates'],1)
        self.assertEqual(len(self.jobs()),1)

    def test_filter_management_is_admin_only(self):
        result=self.client.post('/api/sourcing/filters',json={'companies':['Acme']})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['companies'],['Acme'])
        from tests.web_client import sign_in_bidder
        sign_in_bidder(self.client,1)
        self.assertEqual(self.client.post('/api/sourcing/filters',json={'companies':[]}).status_code,403)

    def test_company_filter_requires_full_name_and_keeps_unrelated_jobs(self):
        filters.set_companies(self.conn,['Acme, Inc.'])
        self.conn.commit()
        result=self.add([['ACME INC','Engineer','https://jobs.test/no'],['Acme Research','Engineer','https://jobs.test/yes']])
        self.assertEqual(result['filtered']['blocked_companies'],1)
        self.assertEqual([r[0]['value'] for r in self.jobs()],['Acme Research'])

    def test_checked_history_and_formatting_are_not_filtered_retroactively(self):
        self.add([['Acme','Engineer','https://jobs.test/old','true']])
        filters.set_companies(self.conn,['Acme'])
        self.conn.commit()
        base=self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Checked rows cannot be edited'):
            self.native.save(self.conn,self.tab(),'format',[{'row_id':base['row_ids'][1],'column_id':base['columns'][0]['id'],'expected_version':base['rows'][1][0]['version'],'style':{'bold':True}}])
        self.assertEqual(len(self.jobs()),1)
        self.assertEqual(self.snapshot()['rows'][1][3]['value'],'true')

    def test_checking_an_incoming_duplicate_does_not_bypass_filter(self):
        self.add([['Acme','Engineer','https://jobs.test/old']])
        base=self.snapshot()
        row=base['row_ids'][-1]
        changes=[{'row_id':row,'column_id':base['columns'][i]['id'],'expected_version':0,'value':v} for i,v in [(3,'true'),(2,'https://jobs.test/old'),(0,'Acme')]]
        result=self.native.save(self.conn,self.tab(),'checked-paste',changes)
        self.assertEqual(result['filtered']['duplicates'],1)
        self.assertEqual(len(self.jobs()),1)

    def test_blocked_company_matches_case_insensitive_substrings_in_new_rows(self):
        self.add([['Acme Consulting','Engineer','https://jobs.test/history']],'history')
        filters.set_companies(self.conn,['aCmE','BETA'])
        self.conn.commit()
        result=self.add([['ACME Inc.','Engineer','https://jobs.test/a'],
                         ['The Acme Consulting Group','Engineer','https://jobs.test/b'],
                         ['Alpha beta Labs','Engineer','https://jobs.test/c'],
                         ['Other Company','Engineer','https://jobs.test/d']])
        self.assertEqual(result['filtered']['blocked_companies'],3)
        self.assertEqual([r[0]['value'] for r in self.jobs()],['Acme Consulting','Other Company'])

    def test_account_role_keywords_are_isolated_and_preserve_existing_rows(self):
        self.add([['Old','MLOps Engineer','https://jobs.test/old']],'old-role')
        filters.set_roles(self.conn,self.account_id,['MLOps','full stack','Machine learning','MLOPS'])
        self.conn.commit()
        result=self.add([['A','Senior mlops Engineer','https://jobs.test/a'],
                         ['B','Full-stack Developer','https://jobs.test/b'],
                         ['C','Machine Learning Engineer','https://jobs.test/c'],
                         ['D','Backend Developer','https://jobs.test/d']],'roles')
        self.assertEqual(result['filtered']['blocked_roles'],3)
        self.assertEqual([r[0]['value'] for r in self.jobs()],['Old','D'])
        other=db.add_account(self.conn,label='role-other',email='other@example.test')
        tab=self.native.owned(self.conn,self.native.create_tab(self.conn,self.book,other,'Other'),self.principal)
        result=self.add([['A','MLOps Engineer','https://jobs.test/a']],'other-role',tab=tab)
        self.assertEqual(result['filtered']['blocked_roles'],0)
        self.assertEqual(len(self.jobs(tab)),1)

    def test_role_completed_after_job_link_is_filtered_but_checked_history_is_kept(self):
        self.add([['A','','https://jobs.test/a']],'incomplete-role')
        filters.set_roles(self.conn,self.account_id,['MLOps']);self.conn.commit()
        base=self.snapshot()
        row=base['row_ids'][1]
        result=self.native.save(self.conn,self.tab(),'role-edit',[{'row_id':row,'column_id':base['columns'][1]['id'],'expected_version':0,'value':'MLOps'}])
        self.assertEqual(result['filtered']['blocked_roles'],1)
        self.add([['Historical','Engineer','https://jobs.test/checked','true']],'checked-role')
        base=self.snapshot();cell=base['rows'][1][1]
        with self.assertRaisesRegex(ValueError, 'Checked rows cannot be edited'):
            self.native.save(self.conn,self.tab(),'checked-role-edit',[{'row_id':base['row_ids'][1],'column_id':base['columns'][1]['id'],'expected_version':cell['version'],'value':'MLOps'}])
        self.assertEqual(len(self.jobs()),1)

    def test_role_filter_api_is_account_scoped_and_admin_only(self):
        response=self.client.post(f'/api/sourcing/role-filters/{self.account_id}',json={'keywords':['MLOps','Full stack']})
        self.assertEqual(response.status_code,200,response.text)
        data=self.client.get('/api/sourcing/role-filters').json()
        self.assertEqual(data['accounts'][0]['keywords'],['Full stack','MLOps'])
        self.assertEqual(self.client.post('/api/sourcing/role-filters/9999',json={'keywords':['MLOps']}).status_code,404)
        from tests.web_client import sign_in_bidder
        sign_in_bidder(self.client,1)
        self.assertEqual(self.client.get('/api/sourcing/role-filters').status_code,403)
        self.assertEqual(self.client.post(f'/api/sourcing/role-filters/{self.account_id}',json={'keywords':[]}).status_code,403)

    def test_role_settings_persist_and_keep_programming_language_symbols(self):
        filters.set_roles(self.conn,self.account_id,['C++','full stack','FULL-STACK'])
        self.conn.commit()
        with db.session(self.path) as reopened:
            self.assertEqual(len(filters.roles(reopened,self.account_id)),2)
        result=self.add([['A','C# Engineer','https://jobs.test/csharp'],['B','Senior C++ Developer','https://jobs.test/cpp'],['C','Fullstack Engineer','https://jobs.test/full']],'symbols')
        self.assertEqual(result['filtered']['blocked_roles'],2)
        self.assertEqual([r[0]['value'] for r in self.jobs()],['A'])

    def test_csv_roles_apply_and_clearing_one_account_leaves_company_filters(self):
        filters.set_companies(self.conn,['Blocked Co'])
        filters.set_roles(self.conn,self.account_id,['MLOps'])
        self.conn.commit()
        result=sourcing_csv.import_rows(self.conn,self.tab(),'role-csv',self.snapshot()['revision'],text='Company,Role,Job link\nAllowed,MLOps Engineer,https://jobs.test/no\nAllowed,Backend Engineer,https://jobs.test/yes')
        self.assertEqual(result['filtered']['blocked_roles'],1)
        filters.set_roles(self.conn,self.account_id,[])
        self.assertEqual(filters.roles(self.conn,self.account_id),[])
        self.assertEqual(filters.companies(self.conn),['Blocked Co'])

    def test_role_schema_upgrade_keeps_existing_company_filters(self):
        filters.set_companies(self.conn,['Keep Co'])
        self.conn.execute("DROP TABLE sourcing_blocked_roles")
        self.conn.execute("PRAGMA user_version=37")
        self.conn.commit()
        with db.session(self.path) as upgraded:
            self.assertEqual(filters.companies(upgraded),['Keep Co'])
            self.assertEqual(filters.roles(upgraded,self.account_id),[])
