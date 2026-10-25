// Reset the synthetic preview's shared preferences between independent UI cases.
exports.resetFavorites=async function(base){
 const data=await (await fetch(base+'/api/favorites')).json();
 const changes=Object.entries(data.groups).flatMap(([key,values])=>values.map(value=>({key,value,present:false})));
 if(changes.length){const response=await fetch(base+'/api/favorites',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':data.token},body:JSON.stringify({id:require('node:crypto').randomUUID(),changes})});if(!response.ok)throw Error('Cannot reset preview favorites');}
};
