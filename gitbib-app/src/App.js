import React, {Component, useState} from 'react';
import gitbib_data from './quantum.json';
import './App.css';


function AuthorList(props) {
  if (props.authors) {
    const listItems = props.authors.map((author) => <li key={author.family + '-' + author.given}>
      {author.family + ', ' + author.given}</li>);
    return <ul className="AuthorList">{listItems}</ul>;
  }
  return <ul/>
}

function Dates(props) {
  return <p className="card-text">
    {props.entry['published-online'] && props.entry['published-online'] + " (online)"}
    {props.entry['published-online'] && props.entry['published-print'] && " -- "}
    {props.entry['published-print'] && props.entry['published-print'] + " (print)"}
  </p>
}

function ContainerTitle(props) {
  return <em>{props.entry['container_title']['full_name']} ({props.entry['container_title']['short_name']})</em>
}

function arb_object_to_str(v) {
  if (typeof v === 'object' && v !== null) {
    v = '[' + Object.keys(v).map((k2) => k2 + ": " + arb_object_to_str(v[k2])).join() + ']';
  }

  return v;
}

function EntryDebugCard(props) {
  let list = [];
  for (let k in props.entry) {
    let v = arb_object_to_str(props.entry[k]);
    list.push((<li key={k}>{k + ': ' + v}</li>))
  }
  return (
      <div className="card-block">
        <ul>{list}</ul>
      </div>
  )
}

function EntryCard(props) {
  const entry = props.entry;

  return <div className="card">
    <div className="card-block">
      <h4 className="card-title">{entry['title']}</h4>
      <h6 className="card-subtitle text-muted"><strong>{entry['ident']}</strong></h6>
      <AuthorList authors={entry['authors']}/>
      <Dates entry={entry}/>
      <p className="card-text">
        {entry['container_title'] && <ContainerTitle entry={entry}/>}
        {entry['volume'] && entry['volume'] + ', '}
        {entry['issue'] && entry['issue'] + ', '}
        {entry['page'] && entry['page'] + '. '}
      </p>
    </div>

    <EntryDebugCard entry={entry}/>

  </div>
}

function sortofMatches(text1, text2) {
  text1 = text1.toLowerCase();
  text2 = text2.toLowerCase();
  return text2.includes(text1);
}

function Entries() {
  const [searchText, setSearchText] = useState("");
  const [entries, setEntries] = useState(gitbib_data);
  const entry_cards = entries.map((entry) => <EntryCard key={entry.ident} entry={entry}/>);

  return <div>
    <input type="text" placeholder="Filter" value={searchText} onChange={
      function (event) {
        let newval = event.target.value;
        setSearchText(newval);
        setEntries(gitbib_data.filter(
            entry => entry['title'] && sortofMatches(newval, entry['title'])))
      }}/>
    {entry_cards}
  </div>;
}


class App extends Component {
  render() {
    return (
        <div className="App">
          <div className="container">
            <div className="row" style={{marginTop: '1rem'}}>
              <div className="col-xs-12 col-lg-9">
                <h5><a className="text-muted" href="user_info['index_url']">
                  <i className="fa fa-home" aria-hidden="true"/>
                  user_info slugname
                </a> |
                  All tags:
                </h5>

                <Entries/>
                <hr style={{margin: '2rem'}}/>
              </div>
            </div>
          </div>
        </div>
    );
  }
}

export default App;
