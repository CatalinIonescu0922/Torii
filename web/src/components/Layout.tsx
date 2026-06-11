import { Link, useLocation } from 'react-router-dom';
import logo from '../assets/white_logo.png'
interface LayoutProps {
  children: React.ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path ? 'text-blue-600 border-b-2 border-blue-600' : 'text-gray-600 hover:text-gray-800';

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-8 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-gray-900"><img src={logo} alt="" height='125px' width='125px'/></h1>
            <nav className="flex gap-8">
              <Link to="/" className={`pb-2 font-medium transition ${isActive('/')}`}>
                Active Status
              </Link>
              <Link to="/buildsets" className={`pb-2 font-medium transition ${isActive('/buildsets')}`}>
                Buildset History
              </Link>
            </nav>
          </div>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-8 py-8">
        {children}
      </main>
    </div>
  );
}
