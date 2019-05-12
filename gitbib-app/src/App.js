import React, {Component, useState, useEffect} from 'react';
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
    if (['ident', 'title', 'authors'].includes(k)) {
      // skip keys we know are good-to-go.
    } else {
      let v = arb_object_to_str(props.entry[k]);
      list.push((<li key={k}>{k + ': ' + v}</li>))
    }
  }
  return (
      <div className="card-block">
        <ul>{list}</ul>
      </div>
  )
}

function DescriptionP(props) {
  const desc = props.desc;
  let parts = [];
  let part_i = 0;
  for (let part of desc.parts) {
    if (part.hasOwnProperty('content')) {
      parts.push(<span key={part_i}>{part['content']}</span>);
    } else if (part['ident']) {
      let text = '[' + part['ident'];
      if (part['num']) {
        text += '=' + part['num'];
      }
      text += ']';
      parts.push(<a href={'#' + part['ident']} key={part_i}>{text}</a>);
    } else if (part['s']) {
      parts.push(<a href={part['href']} key={part_i}>{part['s']}</a>);
    } else {
      throw new Error("Unknown desc part: " + JSON.stringify(part));
    }
    part_i += 1;
  }
  return <p>{parts}</p>
}

function Description(props) {
  if(props.desc == null){
    return null;
  }
  const desc = props.desc.paragraphs || [];
  return desc.map((x, i) => <DescriptionP desc={x} key={i}/>)
}

function EntryCard(props) {
  const entry = props.entry;

  return <div className="card" id={entry['ident']}>
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

      <Description desc={entry['description']}/>
    </div>

    <EntryDebugCard entry={entry}/>

  </div>
}

function sortofMatches(text1, text2) {
  text1 = text1.toLowerCase();
  text2 = text2.toLowerCase();
  return text2.includes(text1);
}

function useFetch(url) {
  const [data, setData] = useState(null);

  async function fetchData() {
    const response = await fetch(url);
    const json = await response.json();
    setData(json);
  }

  useEffect(() => {
    fetchData()
  }, []);
  return data
}

function Entries() {
  const [searchText, setSearchText] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [entries, setEntries] = useState([]);
  const entry_cards = entries.map((entry) => <EntryCard key={entry.ident} entry={entry}/>);

  const gitbib_data = useFetch("http://localhost:8888/entries");
  if (!loaded && gitbib_data) {
    setEntries(gitbib_data['entries']);
    setLoaded(true);
  }

  return <div>
    <input type="text" placeholder="Filter" value={searchText} onChange={
      function (event) {
        let newval = event.target.value;
        setSearchText(newval);
        setEntries(gitbib_data['entries'].filter(
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
